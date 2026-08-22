import { ChangeDetectionStrategy, Component, computed, inject, signal } from '@angular/core';
import { Router, RouterLink } from '@angular/router';
import { forkJoin } from 'rxjs';
import { finalize } from 'rxjs/operators';

import { BootstrapData, DashboardData } from '../core/api.models';
import { SmartCounsellingApiService } from '../core/smart-counselling-api.service';
import { PageHeaderComponent } from '../shared/page-header.component';

interface MetricCard {
  label: string;
  value: number | string;
  icon: string;
  tone: string;
}

@Component({
  selector: 'sc-dashboard',
  imports: [RouterLink, PageHeaderComponent],
  templateUrl: './dashboard.component.html',
  changeDetection: ChangeDetectionStrategy.OnPush,
})
export class DashboardComponent {
  private readonly api = inject(SmartCounsellingApiService);
  private readonly router = inject(Router);

  readonly loading = signal(true);
  readonly error = signal('');
  readonly bootstrap = signal<BootstrapData | null>(null);
  readonly dashboard = signal<DashboardData | null>(null);
  readonly resumingId = signal<number | null>(null);
  readonly metricCards = computed<MetricCard[]>(() => {
    const metrics = this.dashboard()?.metrics;
    if (!metrics) return [];
    return [
      {label: "Today's Sessions", value: metrics.todaySessions, icon: 'bi-calendar2-check', tone: 'indigo'},
      {label: 'Unlinked Sessions', value: metrics.newUnlinkedSessions, icon: 'bi-person-plus', tone: 'green'},
      {label: 'Completed Today', value: metrics.completedSessions, icon: 'bi-check2-circle', tone: 'violet'},
      {label: 'Open Sessions', value: metrics.openSessions, icon: 'bi-arrow-repeat', tone: 'amber'},
      {label: 'Ready for Admission', value: metrics.readyForAdmission ?? '—', icon: 'bi-mortarboard', tone: 'rose'},
    ];
  });

  constructor() {
    this.load();
  }

  load(): void {
    this.loading.set(true);
    this.error.set('');
    forkJoin({bootstrap: this.api.getBootstrap(), dashboard: this.api.getDashboard()})
      .pipe(finalize(() => this.loading.set(false)))
      .subscribe({
        next: ({bootstrap, dashboard}) => {
          this.bootstrap.set(bootstrap);
          this.dashboard.set(dashboard);
          document.documentElement.style.setProperty('--sc-tenant-primary', bootstrap.tenant.primaryColor);
        },
        error: (error: unknown) => {
          this.error.set(error instanceof Error ? error.message : 'Smart Counselling could not be loaded.');
        },
      });
  }

  resume(sessionId: number): void {
    this.resumingId.set(sessionId);
    this.error.set('');
    this.api.resumeSession(sessionId).subscribe({
      next: () => void this.router.navigate(['/session', sessionId, 'verify']),
      error: (error: unknown) => {
        this.resumingId.set(null);
        this.error.set(error instanceof Error ? error.message : 'The session could not be resumed.');
      },
    });
  }
}
