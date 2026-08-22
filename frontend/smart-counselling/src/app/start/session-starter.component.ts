import { ChangeDetectionStrategy, Component, OnInit, inject, signal } from '@angular/core';
import { Router } from '@angular/router';

import { BootstrapData } from '../core/api.models';
import { SmartCounsellingApiError, SmartCounsellingApiService } from '../core/smart-counselling-api.service';

@Component({
  selector: 'sc-session-starter',
  template: `
    <section class="sc-state-card" role="status">
      @if (choosingBranch()) {
        <div class="sc-branch-choice">
          <span class="sc-branch-choice-icon"><i class="bi bi-building" aria-hidden="true"></i></span>
          <strong>Choose a counselling branch</strong>
          <p>The new counselling session will be recorded against this branch.</p>
          @if (error()) { <div class="sc-inline-alert">{{ error() }}</div> }
          <label for="counsellingBranch">Active branch</label>
          <select id="counsellingBranch" [value]="selectedBranchId() ?? ''" (change)="selectBranch($event)">
            <option value="">Select a branch</option>
            @for (branch of branches(); track branch.id) {
              <option [value]="branch.id">{{ branch.name }}</option>
            }
          </select>
          <button class="sc-button sc-button-primary" type="button"
                  [disabled]="!selectedBranchId() || starting()" (click)="startSelectedBranch()">
            {{ starting() ? 'Starting…' : 'Start Counselling' }}
          </button>
        </div>
      } @else if (error()) {
        <div class="sc-start-error">
          <i class="bi bi-exclamation-circle" aria-hidden="true"></i>
          <strong>We could not start counselling.</strong>
          <p>{{ error() }}</p>
          <button class="sc-button sc-button-primary" type="button" (click)="initialize()">Try again</button>
        </div>
      } @else {
        <span class="sc-spinner" aria-hidden="true"></span>
        <strong>Starting a secure counselling session…</strong>
      }
    </section>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class SessionStarterComponent implements OnInit {
  private readonly api = inject(SmartCounsellingApiService);
  private readonly router = inject(Router);
  readonly error = signal('');
  readonly branches = signal<BootstrapData['activeBranches']>([]);
  readonly selectedBranchId = signal<number | null>(null);
  readonly choosingBranch = signal(false);
  readonly starting = signal(false);

  ngOnInit(): void {
    this.initialize();
  }

  initialize(): void {
    this.error.set('');
    this.choosingBranch.set(false);
    this.api.getBootstrap().subscribe({
      next: (bootstrap) => {
        if (!bootstrap.staff.canViewAllBranches) {
          this.createSession(bootstrap.staff.branchId);
          return;
        }
        this.branches.set(bootstrap.activeBranches);
        const assignedBranch = bootstrap.activeBranches.find((branch) => branch.id === bootstrap.staff.branchId);
        this.selectedBranchId.set(assignedBranch?.id ?? null);
        this.choosingBranch.set(true);
        if (!bootstrap.activeBranches.length) {
          this.error.set('No active branches are available for this institute.');
        }
      },
      error: (error: unknown) => this.error.set(this.errorMessage(error)),
    });
  }

  selectBranch(event: Event): void {
    const value = (event.target as HTMLSelectElement).value;
    this.selectedBranchId.set(value ? Number(value) : null);
    this.error.set('');
  }

  startSelectedBranch(): void {
    const branchId = this.selectedBranchId();
    if (!branchId) {
      this.error.set('Choose an active branch before starting counselling.');
      return;
    }
    this.createSession(branchId);
  }

  private createSession(branchId: number | null): void {
    this.error.set('');
    this.starting.set(true);
    this.api.createSession(branchId).subscribe({
      next: (session) => {
        void this.router.navigate(['/session', session.id, 'verify'], {replaceUrl: true});
      },
      error: (error: unknown) => {
        this.starting.set(false);
        this.error.set(this.errorMessage(error));
      },
    });
  }

  private errorMessage(error: unknown): string {
    return error instanceof SmartCounsellingApiError || error instanceof Error
      ? error.message : 'Please try again.';
  }
}
