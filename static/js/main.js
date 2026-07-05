// ContribKit — Main JavaScript

document.addEventListener('DOMContentLoaded', () => {
  initNavbar();
  initTooltips();
  initCopyButtons();
  initSaveToggle();
});

/* ── Navbar scroll + mobile toggle ── */
function initNavbar() {
  const navbar = document.getElementById('navbarApp');
  const toggle = document.getElementById('navbarToggle');
  const mobile = document.getElementById('navbarMobile');

  if (navbar) {
    window.addEventListener('scroll', () => {
      navbar.classList.toggle('is-scrolled', window.scrollY > 8);
    }, { passive: true });
  }

  if (toggle && mobile) {
    toggle.addEventListener('click', () => {
      const isOpen = mobile.classList.toggle('is-open');
      toggle.setAttribute('aria-expanded', isOpen);
      toggle.innerHTML = isOpen
        ? '<i class="bi bi-x-lg fs-5"></i>'
        : '<i class="bi bi-list fs-5"></i>';
    });

    document.addEventListener('click', (e) => {
      if (!navbar.contains(e.target) && mobile.classList.contains('is-open')) {
        mobile.classList.remove('is-open');
        toggle.setAttribute('aria-expanded', 'false');
        toggle.innerHTML = '<i class="bi bi-list fs-5"></i>';
      }
    });
  }
}

/* ── Bootstrap tooltips ── */
function initTooltips() {
  document.querySelectorAll('[data-bs-toggle="tooltip"]').forEach(el => {
    new bootstrap.Tooltip(el);
  });
}

/* ── Copy to clipboard ── */
function initCopyButtons() {
  document.querySelectorAll('.btn-copy').forEach(btn => {
    btn.addEventListener('click', () => {
      const text = btn.getAttribute('data-clipboard-text') || btn.previousElementSibling?.innerText;
      if (!text) return;

      navigator.clipboard.writeText(text).then(() => {
        showToast('Copied to clipboard!', 'success');
        const original = btn.innerHTML;
        btn.innerHTML = '<i class="bi bi-check2"></i> Copied!';
        setTimeout(() => { btn.innerHTML = original; }, 2000);
      }).catch(() => {
        showToast('Failed to copy', 'danger');
      });
    });
  });
}

/* ── Issue save / unsave (AJAX) ── */
function initSaveToggle() {
  document.querySelectorAll('.btn-toggle-save').forEach(btn => {
    btn.addEventListener('click', async (e) => {
      e.preventDefault();
      const issueId = btn.getAttribute('data-issue-id');
      const csrfToken = getCookie('csrftoken');

      try {
        btn.disabled = true;
        const response = await fetch(`/issues/${issueId}/toggle-save/`, {
          method: 'POST',
          headers: {
            'X-CSRFToken': csrfToken,
            'Content-Type': 'application/json',
            'X-Requested-With': 'XMLHttpRequest',
          },
        });
        const data = await response.json();
        btn.disabled = false;

        if (response.status === 403 || data.error === 'login_required') {
          window.location.href = `/accounts/login/?next=${window.location.pathname}`;
          return;
        }

        if (data.status === 'saved') {
          showToast('Issue saved to your dashboard!', 'success');
          btn.classList.remove('btn-secondary', 'btn-outline-primary');
          btn.classList.add('btn-primary');
          if (btn.classList.contains('btn-icon')) {
            btn.innerHTML = '<i class="bi bi-bookmark-fill"></i>';
            btn.title = 'Saved';
          } else {
            btn.innerHTML = '<i class="bi bi-bookmark-fill"></i> Saved';
          }
        } else if (data.status === 'unsaved') {
          showToast('Issue removed from saved.', 'info');
          btn.classList.remove('btn-primary');
          btn.classList.add('btn-secondary');
          if (btn.classList.contains('btn-icon')) {
            btn.innerHTML = '<i class="bi bi-bookmark"></i>';
            btn.title = 'Save issue';
          } else {
            btn.innerHTML = '<i class="bi bi-bookmark"></i> Save Issue';
          }
          const card = btn.closest('.saved-issue-card');
          if (card && window.location.pathname.includes('/dashboard/saved')) {
            card.remove();
            checkEmptySavedList();
          }
        }
      } catch {
        btn.disabled = false;
        showToast('An error occurred. Please try again.', 'danger');
      }
    });
  });
}

/* ── Toast notifications ── */
function showToast(message, type = 'primary') {
  let container = document.getElementById('toastContainer');
  if (!container) {
    container = document.createElement('div');
    container.id = 'toastContainer';
    container.className = 'toast-container position-fixed bottom-0 end-0 p-3';
    document.body.appendChild(container);
  }

  const id = 'toast-' + Date.now();
  const bgClass = {
    success: 'bg-success text-white',
    danger: 'bg-danger text-white',
    info: 'bg-info text-dark',
  }[type] || 'bg-primary text-white';

  container.insertAdjacentHTML('beforeend', `
    <div id="${id}" class="toast align-items-center ${bgClass} border-0" role="alert" aria-live="assertive" aria-atomic="true">
      <div class="d-flex">
        <div class="toast-body fw-medium">${message}</div>
        <button type="button" class="btn-close btn-close-white me-2 m-auto" data-bs-dismiss="toast" aria-label="Close"></button>
      </div>
    </div>
  `);

  const el = document.getElementById(id);
  const toast = new bootstrap.Toast(el, { delay: 3500 });
  toast.show();
  el.addEventListener('hidden.bs.toast', () => el.remove());
}

/* ── CSRF cookie helper ── */
function getCookie(name) {
  if (!document.cookie) return null;
  for (const cookie of document.cookie.split(';')) {
    const trimmed = cookie.trim();
    if (trimmed.startsWith(name + '=')) {
      return decodeURIComponent(trimmed.substring(name.length + 1));
    }
  }
  return null;
}

/* ── Empty saved list fallback ── */
function checkEmptySavedList() {
  const container = document.getElementById('savedIssuesList');
  if (container && container.children.length === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-state-icon"><i class="bi bi-bookmark-x"></i></div>
        <h4>No saved issues</h4>
        <p>You haven't saved any issues yet. Browse the issue board to find beginner opportunities!</p>
        <a href="/issues/" class="btn btn-primary">Browse Issues</a>
      </div>
    `;
  }
}
