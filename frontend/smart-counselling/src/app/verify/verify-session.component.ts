import { ChangeDetectionStrategy, Component, OnDestroy, OnInit, inject, signal } from '@angular/core';
import { FormControl, ReactiveFormsModule, Validators } from '@angular/forms';
import { ActivatedRoute, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';

import { CounsellingSession, IdentificationData, IdentityResolutionData, OtpChallengeSafe, ProspectStatus } from '../core/api.models';
import { SmartCounsellingApiError, SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { CounsellingStepperComponent } from '../shared/counselling-stepper.component';
import { PageHeaderComponent } from '../shared/page-header.component';

type ScreenState = 'MOBILE' | 'OTP' | 'RESULT';

@Component({
  selector: 'sc-verify-session',
  imports: [CounsellingStepperComponent, PageHeaderComponent, ReactiveFormsModule, RouterLink],
  templateUrl: './verify-session.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class VerifySessionComponent implements OnInit, OnDestroy {
  private readonly api = inject(SmartCounsellingApiService);
  private readonly route = inject(ActivatedRoute);
  private timer?: ReturnType<typeof setInterval>;
  private sessionId = 0;

  readonly loading = signal(true);
  readonly busy = signal(false);
  readonly error = signal('');
  readonly screen = signal<ScreenState>('MOBILE');
  readonly session = signal<CounsellingSession | null>(null);
  readonly challenge = signal<OtpChallengeSafe | null>(null);
  readonly identification = signal<IdentificationData | null>(null);
  readonly secondsToResend = signal(0);
  readonly canOverride = signal(false);
  readonly showOverride = signal(false);
  readonly resolution = signal<IdentityResolutionData | null>(null);
  readonly resolutionLoading = signal(false);

  readonly mobile = new FormControl('', {
    nonNullable: true,
    validators: [Validators.required, Validators.pattern(/^[6-9][0-9]{9}$/)],
  });
  readonly otpControls = Array.from({length: 6}, () => new FormControl('', {
    nonNullable: true, validators: [Validators.required, Validators.pattern(/^[0-9]$/)],
  }));
  readonly overrideReason = new FormControl('', {nonNullable: true, validators: [Validators.required]});
  readonly overrideNote = new FormControl('', {nonNullable: true});

  ngOnInit(): void {
    this.sessionId = Number(this.route.snapshot.paramMap.get('sessionId'));
    if (!Number.isInteger(this.sessionId) || this.sessionId < 1) {
      this.error.set('The counselling session link is invalid.');
      this.loading.set(false);
      return;
    }
    forkJoin({
      session: this.api.getSession(this.sessionId),
      otpStatus: this.api.getOtpStatus(this.sessionId),
      bootstrap: this.api.getBootstrap(),
    }).subscribe({
      next: ({session, otpStatus, bootstrap}) => {
        this.session.set(session);
        this.canOverride.set(bootstrap.otp.canOverride);
        if (session.identificationStatus) {
          this.identification.set(this.fromPersistedSession(session));
          this.screen.set('RESULT');
        } else if (otpStatus.activeChallenge) {
          this.challenge.set(otpStatus.activeChallenge);
          this.secondsToResend.set(otpStatus.activeChallenge.resendAvailableInSeconds);
          this.screen.set('OTP');
          this.startCountdown();
        }
        this.loading.set(false);
      },
      error: (error: unknown) => this.fail(error, 'The counselling session could not be loaded.'),
    });
  }

  ngOnDestroy(): void { if (this.timer) clearInterval(this.timer); }

  keepDigitsOnly(): void {
    this.mobile.setValue(this.mobile.value.replace(/\D/g, '').slice(0, 10), {emitEvent: false});
  }

  sendOtp(): void {
    this.mobile.markAsTouched();
    if (this.mobile.invalid || this.busy()) return;
    this.busy.set(true); this.error.set('');
    this.api.sendOtp(this.sessionId, this.mobile.value).subscribe({
      next: (challenge) => {
        this.challenge.set(challenge); this.screen.set('OTP');
        this.secondsToResend.set(challenge.resendAvailableInSeconds);
        this.otpControls.forEach((control) => control.setValue(''));
        this.startCountdown(); this.busy.set(false);
        setTimeout(() => document.getElementById('otp-0')?.focus());
      },
      error: (error: unknown) => this.fail(error, 'The OTP could not be sent.'),
    });
  }

  resendOtp(): void { if (this.secondsToResend() === 0) this.sendOtp(); }

  changeMobile(): void {
    if (this.busy()) return;
    this.busy.set(true); this.error.set('');
    this.api.changeMobile(this.sessionId).subscribe({
      next: () => {
        this.challenge.set(null); this.screen.set('MOBILE'); this.busy.set(false);
        this.otpControls.forEach((control) => control.setValue(''));
      },
      error: (error: unknown) => this.fail(error, 'The mobile number could not be changed.'),
    });
  }

  handleOtpInput(index: number, event: Event): void {
    const input = event.target as HTMLInputElement;
    const digit = input.value.replace(/\D/g, '').slice(-1);
    this.otpControls[index].setValue(digit);
    if (digit && index < 5) document.getElementById(`otp-${index + 1}`)?.focus();
  }

  handleOtpKey(index: number, event: KeyboardEvent): void {
    if (event.key === 'Backspace' && !this.otpControls[index].value && index > 0) {
      document.getElementById(`otp-${index - 1}`)?.focus();
    } else if (event.key === 'ArrowLeft' && index > 0) {
      document.getElementById(`otp-${index - 1}`)?.focus();
    } else if (event.key === 'ArrowRight' && index < 5) {
      document.getElementById(`otp-${index + 1}`)?.focus();
    }
  }

  handleOtpPaste(event: ClipboardEvent): void {
    const digits = event.clipboardData?.getData('text').replace(/\D/g, '').slice(0, 6) ?? '';
    if (!digits) return;
    event.preventDefault();
    digits.split('').forEach((digit, index) => this.otpControls[index].setValue(digit));
    document.getElementById(`otp-${Math.min(digits.length, 6) - 1}`)?.focus();
  }

  verifyOtp(): void {
    const otp = this.otpControls.map((control) => control.value).join('');
    if (otp.length !== 6 || !this.challenge() || this.busy()) return;
    this.busy.set(true); this.error.set('');
    this.api.verifyOtp(this.sessionId, this.challenge()!.challengeId, otp).subscribe({
      next: (result) => {
        this.identification.set(result); this.screen.set('RESULT'); this.busy.set(false);
        this.session.update((session) => session ? ({...session, identificationStatus: result.prospect.status}) : session);
      },
      error: (error: unknown) => {
        this.otpControls.forEach((control) => control.setValue(''));
        this.fail(error, 'The OTP could not be verified.');
      },
    });
  }

  submitOverride(): void {
    this.mobile.markAsTouched(); this.overrideReason.markAsTouched();
    if (this.mobile.invalid || this.overrideReason.invalid || this.busy()) return;
    this.busy.set(true); this.error.set('');
    this.api.overrideOtp(this.sessionId, this.mobile.value, this.overrideReason.value, this.overrideNote.value).subscribe({
      next: (result) => { this.identification.set(result); this.screen.set('RESULT'); this.busy.set(false); },
      error: (error: unknown) => this.fail(error, 'The override could not be recorded.'),
    });
  }

  loadIdentityResolution(): void {
    if (this.resolutionLoading()) return;
    this.resolutionLoading.set(true); this.error.set('');
    this.api.getIdentityResolution(this.sessionId).subscribe({
      next: (resolution) => { this.resolution.set(resolution); this.resolutionLoading.set(false); },
      error: (error: unknown) => { this.resolutionLoading.set(false); this.fail(error, 'CRM matches could not be loaded.'); },
    });
  }

  confirmIdentity(leadId: number): void {
    if (this.busy()) return;
    this.busy.set(true); this.error.set('');
    this.api.confirmIdentityResolution(this.sessionId, leadId).subscribe({
      next: (result) => {
        this.identification.set(result); this.resolution.set(null); this.busy.set(false);
        this.session.update((session) => session ? ({
          ...session,
          status: 'IDENTIFIED',
          identificationStatus: result.prospect.status,
          prospect: result.prospect.lead ? {id: result.prospect.lead.id, name: result.prospect.lead.name} : null,
        }) : session);
      },
      error: (error: unknown) => this.fail(error, 'The CRM identity could not be confirmed.'),
    });
  }

  useDifferentMobile(): void {
    this.changeMobile();
    this.identification.set(null); this.resolution.set(null); this.mobile.setValue('');
  }

  resultTitle(status: ProspectStatus): string {
    return ({
      NEW: 'New Prospect', EXISTING_LEAD: 'Welcome Back', EXISTING_STUDENT: 'Existing Student',
      EXISTING_LEAD_RESTRICTED: 'Existing Prospect Found', MULTIPLE_MATCHES: 'Multiple CRM Matches',
      SOFT_DELETED_MATCH: 'Archived Prospect Found',
      UNVERIFIED_MATCH_REQUIRES_CONFIRMATION: 'Identity Confirmation Required',
      UNVERIFIED_NEW: 'Unverified Prospect',
    })[status];
  }

  private fromPersistedSession(session: CounsellingSession): IdentificationData {
    return {
      verification: {verified: session.mobileVerified, method: session.verificationMethod === 'OTP' ? 'OTP' : 'OVERRIDE', mobileMasked: session.mobileMasked ?? ''},
      prospect: {
        status: session.identificationStatus!,
        lead: session.prospect ? {id: session.prospect.id, name: session.prospect.name, mobileMasked: session.mobileMasked ?? '', stage: null} : null,
        matches: [],
      },
      nextStep: ['NEW', 'EXISTING_LEAD', 'UNVERIFIED_NEW'].includes(session.identificationStatus!) ? 'PROFILE' : 'RESOLUTION',
    };
  }

  private startCountdown(): void {
    if (this.timer) clearInterval(this.timer);
    this.timer = setInterval(() => this.secondsToResend.update((value) => Math.max(0, value - 1)), 1000);
  }

  private fail(error: unknown, fallback: string): void {
    this.error.set(error instanceof SmartCounsellingApiError || error instanceof Error ? error.message : fallback);
    this.busy.set(false); this.loading.set(false);
  }
}
