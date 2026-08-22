import { describe, expect, it } from 'vitest';
import { TestBed } from '@angular/core/testing';
import { ActivatedRoute } from '@angular/router';

import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { VerifySessionComponent } from './verify-session.component';

describe('VerifySessionComponent', () => {
  function component(): VerifySessionComponent {
    TestBed.configureTestingModule({
      providers: [
        {provide: ActivatedRoute, useValue: {snapshot: {paramMap: {get: () => '12'}}}},
        {provide: SmartCounsellingApiService, useValue: {}},
      ],
    });
    return TestBed.runInInjectionContext(() => new VerifySessionComponent());
  }

  it('accepts a normalized Indian mobile number', () => {
    const subject = component();
    subject.mobile.setValue('9876543210');
    expect(subject.mobile.valid).toBe(true);
  });

  it('removes non-digits and limits the value to ten digits', () => {
    const subject = component();
    subject.mobile.setValue('98 765-43210 extra');
    subject.keepDigitsOnly();
    expect(subject.mobile.value).toBe('9876543210');
  });

  it('requires every OTP position to contain one numeric digit', () => {
    const subject = component();
    subject.otpControls.forEach((control, index) => control.setValue(index < 5 ? '1' : 'x'));
    expect(subject.otpControls.every((control) => control.valid)).toBe(false);
    subject.otpControls[5].setValue('6');
    expect(subject.otpControls.every((control) => control.valid)).toBe(true);
  });
});
