import { ChangeDetectionStrategy, Component } from '@angular/core';
import { RouterOutlet } from '@angular/router';

@Component({
  selector: 'smart-counselling-root',
  imports: [RouterOutlet],
  template: '<main class="sc-app" aria-label="Smart Counselling"><router-outlet /></main>',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class AppComponent {}
