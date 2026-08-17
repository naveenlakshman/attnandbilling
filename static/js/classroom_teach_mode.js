/**
 * Trainer Classroom Teaching Mode - Presenter JavaScript Module
 * Tabs: Watch Video | Read Tutorial only
 */

(function () {
  'use strict';

  let currentTopicElem = null;
  let topicElementsList = [];
  let programId = 0;
  let batchId = 0;
  let totalTopics = 0;
  let taughtCount = 0;

  function initApp() {
    const appContainer = document.getElementById('classroomTeachApp');
    if (!appContainer) return;

    programId = parseInt(appContainer.getAttribute('data-program-id') || '0', 10);
    batchId = parseInt(appContainer.getAttribute('data-batch-id') || '0', 10);
    totalTopics = parseInt(appContainer.getAttribute('data-total-topics') || '0', 10);
    taughtCount = parseInt(appContainer.getAttribute('data-taught-count') || '0', 10);

    // Projector mode toggle
    const projectorBtn = document.getElementById('projector-toggle-btn');
    if (projectorBtn) projectorBtn.addEventListener('click', toggleProjectorMode);

    // Sidebar toggle (Topics button)
    const toggleSidebarBtn = document.getElementById('toggle-sidebar-btn');
    if (toggleSidebarBtn) toggleSidebarBtn.addEventListener('click', toggleTopicsSidebar);

    // Mark taught button
    const markTaughtBtn = document.getElementById('mark-taught-btn');
    if (markTaughtBtn) markTaughtBtn.addEventListener('click', toggleTaughtStatus);

    // Navigation buttons
    const prevBtn = document.getElementById('prev-topic-btn');
    if (prevBtn) prevBtn.addEventListener('click', function () { navigateTopic(-1); });

    const nextBtn = document.getElementById('next-topic-btn');
    if (nextBtn) nextBtn.addEventListener('click', function () { navigateTopic(1); });

    // Program switcher
    const programSelect = document.getElementById('programSwitcherSelect');
    if (programSelect) {
      programSelect.addEventListener('change', function () {
        if (this.value) window.location.href = '?program_id=' + encodeURIComponent(this.value);
      });
    }

    // Tab buttons — direct click listeners on the two tabs
    const tabWatch = document.getElementById('tabWatch');
    if (tabWatch) tabWatch.addEventListener('click', function () { switchTab('watch'); });

    const tabRead = document.getElementById('tabRead');
    if (tabRead) tabRead.addEventListener('click', function () { switchTab('read'); });

    // Syllabus topic list items
    topicElementsList = Array.from(document.querySelectorAll('.syllabus-topic-item'));
    topicElementsList.forEach(function (elem) {
      elem.addEventListener('click', function () { loadTopic(elem); });
    });

    // Chapter accordion — use event delegation on the scroll body
    var syllabusBody = document.querySelector('.syllabus-scroll-body');
    if (syllabusBody) {
      syllabusBody.addEventListener('click', function (e) {
        var header = e.target.closest('.teach-chapter-header');
        if (!header) return;
        var topicsEl = header.nextElementSibling;
        var isOpen = header.classList.contains('open');
        if (isOpen) {
          header.classList.remove('open');
          if (topicsEl) topicsEl.classList.remove('open');
        } else {
          header.classList.add('open');
          if (topicsEl) topicsEl.classList.add('open');
        }
      });
    }

    if (topicElementsList.length > 0) {
      const initialTopicId = appContainer.getAttribute('data-initial-topic-id');
      const initialTopicIsMaster = appContainer.getAttribute('data-initial-topic-is-master');
      const initialTopicElem = topicElementsList.find(function (elem) {
        return elem.getAttribute('data-topic-id') === initialTopicId &&
          elem.getAttribute('data-is-master') === initialTopicIsMaster;
      }) || topicElementsList[0];

      const initialTopicsGroup = initialTopicElem.closest('.teach-chapter-topics');
      const initialChapterHeader = initialTopicsGroup ? initialTopicsGroup.previousElementSibling : null;
      if (initialTopicsGroup) initialTopicsGroup.classList.add('open');
      if (initialChapterHeader) initialChapterHeader.classList.add('open');

      loadTopic(initialTopicElem);
      initialTopicElem.scrollIntoView({ block: 'nearest' });
    }
  }

  /* ── PROJECTOR MODE ─────────────────────────────────────────────── */

  function toggleProjectorMode() {
    const isProjector = document.body.classList.toggle('projector-mode');
    document.documentElement.classList.toggle('projector-mode', isProjector);

    const btn = document.getElementById('projector-toggle-btn');
    const sidebar = document.getElementById('erpSidebar');
    const topbar = document.querySelector('.erp-topbar');
    const erpMain = document.querySelector('.erp-main');
    const erpShell = document.querySelector('.erp-shell');
    const sidebarBackdrop = document.getElementById('erpSidebarBackdrop');

    if (isProjector) {
      if (sidebar) {
        sidebar.style.setProperty('display', 'none', 'important');
        sidebar.style.setProperty('width', '0', 'important');
        sidebar.style.setProperty('visibility', 'hidden', 'important');
        sidebar.style.setProperty('overflow', 'hidden', 'important');
        sidebar.style.setProperty('position', 'absolute', 'important');
      }
      if (topbar) {
        topbar.style.setProperty('display', 'none', 'important');
        topbar.style.setProperty('visibility', 'hidden', 'important');
      }
      if (sidebarBackdrop) sidebarBackdrop.style.setProperty('display', 'none', 'important');
      if (erpShell) {
        erpShell.style.setProperty('display', 'block', 'important');
        erpShell.style.setProperty('padding', '0', 'important');
        erpShell.style.setProperty('margin', '0', 'important');
      }
      if (erpMain) {
        erpMain.style.setProperty('margin-left', '0', 'important');
        erpMain.style.setProperty('padding', '0', 'important');
        erpMain.style.setProperty('width', '100vw', 'important');
        erpMain.style.setProperty('max-width', '100vw', 'important');
      }
      if (btn) btn.innerHTML = '<span>🔙</span> <span>Exit Projector Mode</span>';
    } else {
      if (sidebar) {
        sidebar.style.removeProperty('display');
        sidebar.style.removeProperty('width');
        sidebar.style.removeProperty('visibility');
        sidebar.style.removeProperty('overflow');
        sidebar.style.removeProperty('position');
      }
      if (topbar) {
        topbar.style.removeProperty('display');
        topbar.style.removeProperty('visibility');
      }
      if (sidebarBackdrop) sidebarBackdrop.style.removeProperty('display');
      if (erpShell) {
        erpShell.style.removeProperty('display');
        erpShell.style.removeProperty('padding');
        erpShell.style.removeProperty('margin');
      }
      if (erpMain) {
        erpMain.style.removeProperty('margin-left');
        erpMain.style.removeProperty('padding');
        erpMain.style.removeProperty('width');
        erpMain.style.removeProperty('max-width');
      }
      if (btn) btn.innerHTML = '<span>📺</span> <span>Projector Mode</span>';
    }
  }

  /* ── TOPICS SIDEBAR TOGGLE ──────────────────────────────────────── */

  function toggleTopicsSidebar() {
    const sidebarCol = document.getElementById('syllabus-sidebar-col');
    const stageCol = document.getElementById('stage-content-col');
    const toggleBtn = document.getElementById('toggle-sidebar-btn');

    if (!sidebarCol || !stageCol) return;

    const isHidden = sidebarCol.classList.toggle('d-none');
    if (isHidden) {
      stageCol.className = 'col-12';
      if (toggleBtn) {
        toggleBtn.classList.add('btn-primary');
        toggleBtn.classList.remove('btn-outline-light');
      }
    } else {
      stageCol.className = 'col-lg-8 col-xl-9';
      if (toggleBtn) {
        toggleBtn.classList.remove('btn-primary');
        toggleBtn.classList.add('btn-outline-light');
      }
    }
  }

  /* ── TAB SWITCHER (Watch / Read only) ──────────────────────────── */

  function switchTab(tabName) {
    // Deactivate all tabs and panes
    ['watch', 'read'].forEach(function (t) {
      var btn = document.getElementById('tab' + capitalize(t));
      var pane = document.getElementById('pane' + capitalize(t));
      if (btn) btn.classList.remove('active');
      if (pane) {
        pane.classList.remove('active');
        pane.style.display = 'none';
      }
    });

    // Activate the requested tab
    var activeBtn = document.getElementById('tab' + capitalize(tabName));
    var activePane = document.getElementById('pane' + capitalize(tabName));
    if (activeBtn) activeBtn.classList.add('active');
    if (activePane) {
      activePane.classList.add('active');
      activePane.style.display = 'block';
    }
  }

  function capitalize(str) {
    return str.charAt(0).toUpperCase() + str.slice(1);
  }

  /* ── LOAD TOPIC ─────────────────────────────────────────────────── */

  function loadTopic(elem) {
    if (currentTopicElem) currentTopicElem.classList.remove('active');
    currentTopicElem = elem;
    elem.classList.add('active');

    const chTitle = elem.getAttribute('data-chapter-title') || 'Chapter';
    const title = elem.getAttribute('data-title') || 'Topic';
    const summary = elem.getAttribute('data-summary');
    const videoUrl = elem.getAttribute('data-video-url');
    const content = elem.getAttribute('data-content');
    const isTaught = elem.getAttribute('data-is-taught') === '1';

    // Update breadcrumb & heading
    const chBreadcrumb = document.getElementById('current-chapter-breadcrumb');
    if (chBreadcrumb) chBreadcrumb.innerText = chTitle;

    const tBreadcrumb = document.getElementById('current-topic-breadcrumb');
    if (tBreadcrumb) tBreadcrumb.innerText = title;

    const tTitle = document.getElementById('current-topic-title');
    if (tTitle) tTitle.innerText = title;

    // Summary box
    const summaryBox = document.getElementById('topic-summary-box');
    const summaryContent = document.getElementById('current-topic-summary');
    if (summary && summary.trim()) {
      if (summaryContent) summaryContent.innerText = summary;
      if (summaryBox) summaryBox.classList.remove('d-none');
    } else {
      if (summaryBox) summaryBox.classList.add('d-none');
    }

    // Watch tab — YouTube embed
    const videoIframe = document.getElementById('video-iframe');
    const videoBox = document.getElementById('video-container-box');
    const noVideoMsg = document.getElementById('no-video-msg');
    const tabWatch = document.getElementById('tabWatch');

    if (videoUrl && videoUrl.trim()) {
      // Build embed URL for the iframe
      let embedUrl = videoUrl;
      if (videoUrl.includes('youtube.com/watch?v=')) {
        embedUrl = videoUrl.replace('watch?v=', 'embed/');
      } else if (videoUrl.includes('youtu.be/')) {
        embedUrl = 'https://www.youtube.com/embed/' + videoUrl.split('youtu.be/')[1];
      }
      if (videoIframe) videoIframe.src = embedUrl;
      if (videoBox) videoBox.classList.remove('d-none');
      if (noVideoMsg) noVideoMsg.classList.add('d-none');
      if (tabWatch) tabWatch.classList.remove('disabled');
    } else {
      if (videoIframe) videoIframe.src = '';
      if (videoBox) videoBox.classList.add('d-none');
      if (noVideoMsg) noVideoMsg.classList.remove('d-none');
      if (tabWatch) tabWatch.classList.add('disabled');
    }

    // Read tab — rich text content
    const richBox = document.getElementById('rich-content-box');
    const noReadMsg = document.getElementById('no-read-msg');
    const tabRead = document.getElementById('tabRead');

    if (content && content.trim()) {
      if (richBox) {
        richBox.innerHTML = content;
        // Ensure images stay responsive without stretching small images to 100% width
        richBox.querySelectorAll('img').forEach(function (img) {
          img.style.maxWidth = '100%';
          img.style.maxHeight = '450px';
          img.style.height = 'auto';
          img.style.objectFit = 'contain';
        });
        // Wrap tables in responsive containers
        richBox.querySelectorAll('table').forEach(function (table) {
          if (!table.parentElement.classList.contains('table-responsive')) {
            var wrapper = document.createElement('div');
            wrapper.className = 'table-responsive';
            table.parentNode.insertBefore(wrapper, table);
            wrapper.appendChild(table);
          }
          table.classList.add('table', 'table-bordered', 'table-hover');
        });
        richBox.classList.remove('d-none');
      }
      if (noReadMsg) noReadMsg.classList.add('d-none');
      if (tabRead) tabRead.classList.remove('disabled');
    } else {
      if (richBox) { richBox.innerHTML = ''; richBox.classList.add('d-none'); }
      if (noReadMsg) noReadMsg.classList.remove('d-none');
      if (tabRead) tabRead.classList.add('disabled');
    }

    // Default to read if content exists, else watch
    if (content && content.trim()) {
      switchTab('read');
    } else {
      switchTab('watch');
    }

    updateMarkTaughtBtnUI(isTaught);
    updateNavButtonsState();
  }

  /* ── MARK TAUGHT BUTTON ─────────────────────────────────────────── */

  function updateMarkTaughtBtnUI(isTaught) {
    const btn = document.getElementById('mark-taught-btn');
    const text = document.getElementById('mark-taught-text');
    if (!btn || !text) return;
    if (isTaught) {
      btn.className = 'btn btn-outline-success fw-bold px-4 py-2';
      text.innerText = '✓ Taught for Batch';
    } else {
      btn.className = 'btn btn-success fw-bold px-4 py-2';
      text.innerText = 'Mark Taught for Batch ✓';
    }
  }

  /* ── NAVIGATION ─────────────────────────────────────────────────── */

  function navigateTopic(dir) {
    if (!currentTopicElem || topicElementsList.length === 0) return;
    const idx = topicElementsList.indexOf(currentTopicElem);
    const targetIdx = idx + dir;
    if (targetIdx >= 0 && targetIdx < topicElementsList.length) {
      loadTopic(topicElementsList[targetIdx]);
    }
  }

  function updateNavButtonsState() {
    if (!currentTopicElem || topicElementsList.length === 0) return;
    const idx = topicElementsList.indexOf(currentTopicElem);
    const prevBtn = document.getElementById('prev-topic-btn');
    const nextBtn = document.getElementById('next-topic-btn');
    if (prevBtn) prevBtn.disabled = (idx <= 0);
    if (nextBtn) nextBtn.disabled = (idx >= topicElementsList.length - 1);
  }

  /* ── TOGGLE TAUGHT STATUS (AJAX) ────────────────────────────────── */

  function toggleTaughtStatus() {
    if (!currentTopicElem) return;

    const topicId = currentTopicElem.getAttribute('data-topic-id');
    const isMaster = currentTopicElem.getAttribute('data-is-master') === '1';
    const isTaught = currentTopicElem.getAttribute('data-is-taught') === '1';

    const payload = { program_id: programId, status: isTaught ? 'pending' : 'taught' };
    if (isMaster) {
      payload.master_topic_id = parseInt(topicId, 10);
    } else {
      payload.topic_id = parseInt(topicId, 10);
    }

    fetch('/lms_admin/batch/' + batchId + '/mark-topic-taught', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload)
    })
      .then(function (r) { return r.json(); })
      .then(function (res) {
        if (res.success) {
          currentTopicElem.setAttribute('data-is-taught', res.is_taught ? '1' : '0');
          const checkEl = currentTopicElem.querySelector('.syllabus-check-icon');
          if (res.is_taught) {
            currentTopicElem.classList.add('done');
            if (checkEl) checkEl.innerText = '✓';
          } else {
            currentTopicElem.classList.remove('done');
            if (checkEl) checkEl.innerText = '';
          }
          updateMarkTaughtBtnUI(res.is_taught);

          taughtCount = res.taught_cnt;
          const pct = totalTopics > 0 ? ((taughtCount / totalTopics) * 100).toFixed(1) : '0';

          const countEl = document.getElementById('batch-taught-count');
          if (countEl) countEl.innerText = taughtCount;

          const pctEl = document.getElementById('batch-taught-pct');
          if (pctEl) pctEl.innerText = pct;

          const headerBar = document.getElementById('batch-progress-bar');
          if (headerBar) headerBar.style.width = pct + '%';

          const sidebarBar = document.getElementById('sidebar-progress-bar');
          if (sidebarBar) sidebarBar.style.width = pct + '%';
        } else {
          alert('Error: ' + (res.message || 'Failed to update topic status'));
        }
      })
      .catch(function (err) {
        console.error(err);
        alert('Network error while updating topic status');
      });
  }

  document.addEventListener('DOMContentLoaded', initApp);
})();
