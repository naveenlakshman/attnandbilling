document.addEventListener('DOMContentLoaded', function () {
  const container = document.getElementById('batchCardsContainer');
  const cards = Array.from(container?.querySelectorAll('.batch-card-col') || []);
  const buttons = Array.from(document.querySelectorAll('[data-classroom-view]'));
  const searchInput = document.getElementById('batchSearchInput');
  const attendanceFilter = document.getElementById('attendanceStatusFilter');
  const classFilter = document.getElementById('classStatusFilter');
  const storageKey = 'classroomTeachingView';
  let currentView = 'cards';
  cards.forEach((card, index) => { card.dataset.originalOrder = String(index); });

  function updateLiveBatches() {
    const current = new Date();
    const now = String(current.getHours()).padStart(2, '0') + ':' + String(current.getMinutes()).padStart(2, '0');
    cards.forEach(function (card) {
      const {start, end} = card.dataset;
      const isLive = Boolean(start && end && now >= start && now < end);
      card.dataset.isLive = isLive ? '1' : '0';
      card.querySelector('.classroom-batch-card')?.classList.toggle('running-now', isLive);
      card.querySelectorAll('.live-badge-classroom').forEach(badge => badge.classList.toggle('d-none', !isLive));
    });
    cards.slice().sort(function (left, right) {
      const liveOrder = Number(right.dataset.isLive) - Number(left.dataset.isLive);
      if (liveOrder) return liveOrder;
      if (currentView === 'list') {
        const timeOrder = (left.dataset.start || '99:99').localeCompare(right.dataset.start || '99:99');
        if (timeOrder) return timeOrder;
      }
      return Number(left.dataset.originalOrder) - Number(right.dataset.originalOrder);
    }).forEach(card => container.appendChild(card));
  }

  function setView(view, remember) {
    currentView = view === 'list' ? 'list' : 'cards';
    container?.classList.toggle('classroom-view-list', currentView === 'list');
    buttons.forEach(function (button) {
      const selected = button.dataset.classroomView === currentView;
      button.setAttribute('aria-pressed', String(selected));
      button.classList.toggle('active', selected);
    });
    const viewField = document.getElementById('classroomViewField');
    if (viewField) viewField.value = currentView;
    if (remember) {
      try { window.localStorage.setItem(storageKey, currentView); } catch (_) { /* Storage is optional. */ }
      const url = new URL(window.location.href);
      url.searchParams.set('view', currentView);
      window.history.replaceState(null, '', url);
    }
    updateLiveBatches();
  }

  function applyBatchFilters() {
    const query = (searchInput?.value || '').toLowerCase().trim();
    const attendanceStatus = attendanceFilter?.value || 'all';
    const classStatus = classFilter?.value || 'all';
    let visibleCount = 0;
    let visibleStudentCount = 0;
    cards.forEach(function (card) {
      const matchesSearch = !query || (card.dataset.searchText || '').includes(query);
      const matchesAttendance = attendanceStatus === 'all' || card.dataset.attendanceStatus === attendanceStatus;
      const matchesClass = classStatus === 'all' || card.dataset.classStatus === classStatus;
      const visible = matchesSearch && matchesAttendance && matchesClass;
      card.style.display = visible ? '' : 'none';
      if (visible) {
        visibleCount++;
        visibleStudentCount += Number(card.dataset.studentCount || 0);
      }
    });
    const batchBadge = document.getElementById('activeBatchCountBadge');
    const studentBadge = document.getElementById('activeStudentCountBadge');
    if (batchBadge) batchBadge.textContent = visibleCount + ' Active Batches';
    if (studentBadge) studentBadge.textContent = visibleStudentCount + ' Total Students';
    document.getElementById('batchNoMatches')?.classList.toggle('d-none', visibleCount > 0);
  }

  let preferredView;
  try { preferredView = window.localStorage.getItem(storageKey); } catch (_) { /* Storage is optional. */ }
  const requestedView = new URL(window.location.href).searchParams.get('view');
  setView(['cards', 'list'].includes(requestedView) ? requestedView : preferredView, false);
  buttons.forEach(button => button.addEventListener('click', () => setView(button.dataset.classroomView, true)));
  searchInput?.addEventListener('input', applyBatchFilters);
  attendanceFilter?.addEventListener('change', applyBatchFilters);
  classFilter?.addEventListener('change', applyBatchFilters);
  applyBatchFilters();
  window.setInterval(updateLiveBatches, 60000);
});
