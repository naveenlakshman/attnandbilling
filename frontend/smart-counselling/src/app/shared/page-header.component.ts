import { ChangeDetectionStrategy, Component, input } from '@angular/core';

@Component({
  selector: 'sc-page-header',
  template: `
    <header class="sc-page-header">
      <div>
        @if (eyebrow()) { <p class="sc-eyebrow">{{ eyebrow() }}</p> }
        <h1>{{ title() }}</h1>
        <p>{{ description() }}</p>
      </div>
      <div class="sc-page-actions"><ng-content /></div>
    </header>
  `,
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class PageHeaderComponent {
  readonly eyebrow = input('');
  readonly title = input.required<string>();
  readonly description = input.required<string>();
}
