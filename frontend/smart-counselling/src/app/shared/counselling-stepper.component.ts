import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'sc-counselling-stepper',
  template: `
    <nav class="sc-stepper" aria-label="Counselling progress">
      @for (step of steps; track step.number) {
        <div class="sc-step" [class.is-active]="step.number === current()" [class.is-complete]="step.number < current()">
          <span class="sc-step-number">{{ step.number }}</span>
          <span class="sc-step-label">{{ step.label }}</span>
        </div>
      }
    </nav>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class CounsellingStepperComponent {
  readonly current = input(1);
  readonly steps = [
    {number: 1, label: 'Verify'},
    {number: 2, label: 'Profile'},
    {number: 3, label: 'Goals'},
    {number: 4, label: 'Skills'},
    {number: 5, label: 'Courses'},
    {number: 6, label: 'Compare'},
    {number: 7, label: 'Outcome'},
  ];
}
