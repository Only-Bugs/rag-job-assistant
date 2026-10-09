/**
 * ResuMate — Shared frontend utilities + UI components.
 * Include in every page:
 *   <link rel="stylesheet" href="/static/shared/styles.css">
 *   <script src="/static/shared/common.js"></script>
 */

// ── 401-aware fetch wrapper ─────────────────────────────────────
async function apiFetch(url, opts = {}) {
  const res = await fetch(url, opts);
  if (res.status === 401) {
    window.location.href = '/login';
    throw new Error('Unauthenticated');
  }
  return res;
}

// ── Load current user ───────────────────────────────────────────
let _cachedUser = null;

async function loadUser() {
  if (_cachedUser) return _cachedUser;
  try {
    const res = await fetch('/auth/me');
    if (res.status === 401) return null;
    if (!res.ok) return null;
    _cachedUser = await res.json();
    return _cachedUser;
  } catch (_) {
    return null;
  }
}

// ── Avatar helper — Google picture with outline icon fallback ────
const _AVATAR_FALLBACK_SVG = `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="6.5" r="3"/><path d="M3 16.5c0-3.31 2.69-6 6-6s6 2.69 6 6"/></svg>`;

function _setAvatar(el, pictureUrl, initials) {
  if (pictureUrl) {
    const img = document.createElement('img');
    img.src = pictureUrl;
    img.alt = '';
    img.referrerPolicy = 'no-referrer';
    img.style.cssText = 'width:100%;height:100%;object-fit:cover;border-radius:inherit;';
    img.onerror = () => { el.innerHTML = _AVATAR_FALLBACK_SVG; img.remove(); };
    el.textContent = '';
    el.appendChild(img);
  } else {
    el.innerHTML = _AVATAR_FALLBACK_SVG;
  }
}

// ── Header injection ────────────────────────────────────────────
function injectHeader(opts = {}) {
  const target = document.getElementById('rm-header-slot');
  if (!target) return;

  const nav = opts.nav || [];
  const navHtml = nav.map(n =>
    `<a class="rm-nav-link" href="${n.href}">${n.label}</a>`
  ).join('');

  target.innerHTML = `
    <header class="rm-header">
      <div class="rm-header-left">
        <a href="/" class="rm-logo">Resu<span>Mate</span></a>
        ${navHtml}
      </div>
      <div class="rm-user-menu" id="rm-user-menu" style="display:none;">
        <button class="rm-avatar" id="rm-avatar-btn" title="Account"></button>
        <div class="rm-dropdown" id="rm-dropdown">
          <a href="/settings">Settings</a>
          <div class="rm-divider"></div>
          <a href="/auth/logout">Sign Out</a>
        </div>
      </div>
    </header>
  `;

  const avatarBtn = document.getElementById('rm-avatar-btn');
  const dropdown = document.getElementById('rm-dropdown');
  if (avatarBtn && dropdown) {
    avatarBtn.addEventListener('click', (e) => {
      e.stopPropagation();
      dropdown.classList.toggle('open');
    });
    document.addEventListener('click', () => dropdown.classList.remove('open'));
  }

  loadUser().then(user => {
    if (!user) return;
    const name = user.name || user.email || '';
    if (name) {
      const initials = name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase();
      const menu = document.getElementById('rm-user-menu');
      const btn = document.getElementById('rm-avatar-btn');
      if (btn) _setAvatar(btn, user.picture, initials);
      if (menu) menu.style.display = '';
    }
  });
}

// ── Footer injection ────────────────────────────────────────────
function injectFooter() {
  const target = document.getElementById('rm-footer-slot');
  if (!target) return;
  const year = new Date().getFullYear();
  target.innerHTML = `
    <footer class="rm-footer">
      ResuMate &copy; ${year} &middot; Built with local AI
    </footer>
  `;
}

// ── Toast notifications ─────────────────────────────────────────
function showToast(message, type = 'success', duration = 3000) {
  let container = document.querySelector('.toast-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-container';
    document.body.appendChild(container);
  }
  const icon = type === 'success' ? '\u2713' : '\u2717';
  const toast = document.createElement('div');
  toast.className = `toast ${type}`;
  toast.innerHTML = `<span class="toast-icon">${icon}</span><span>${message}</span>`;
  container.appendChild(toast);
  setTimeout(() => {
    toast.style.animation = 'toastOut 0.25s ease forwards';
    setTimeout(() => toast.remove(), 250);
  }, duration);
}

// ═══════════════════════════════════════════════════════════════════
// ChipInput — reusable tag/chip input component
// ═══════════════════════════════════════════════════════════════════
class ChipInput {
  /**
   * @param {HTMLElement} container — the wrapper element
   * @param {Object} opts
   * @param {string} opts.placeholder
   * @param {string} opts.type — 'default' | 'link'
   * @param {Function} opts.onChange — called with current values array
   */
  constructor(container, opts = {}) {
    this.container = container;
    this.type = opts.type || 'default';
    this.placeholder = opts.placeholder || 'Type and press Enter';
    this.onChange = opts.onChange || (() => {});
    this.chips = [];

    this.wrap = document.createElement('div');
    this.wrap.className = 'chip-input-wrap';

    this.input = document.createElement('input');
    this.input.type = 'text';
    this.input.className = 'chip-input';
    this.input.placeholder = this.placeholder;

    this.wrap.appendChild(this.input);
    this.container.appendChild(this.wrap);

    this.countEl = document.createElement('div');
    this.countEl.className = 'chip-count';
    this.container.appendChild(this.countEl);

    this._bindEvents();
    this._updateCount();
  }

  _bindEvents() {
    this.wrap.addEventListener('click', () => this.input.focus());

    this.input.addEventListener('keydown', (e) => {
      if ((e.key === 'Enter' || e.key === ',') && this.input.value.trim()) {
        e.preventDefault();
        this.add(this.input.value.trim());
        this.input.value = '';
      }
      if (e.key === 'Backspace' && !this.input.value && this.chips.length) {
        this.removeAt(this.chips.length - 1);
      }
    });

    // Handle paste — split by newlines and commas
    this.input.addEventListener('paste', (e) => {
      e.preventDefault();
      const text = (e.clipboardData || window.clipboardData).getData('text');
      const items = text.split(/[\n,]+/).map(s => s.trim()).filter(Boolean);
      items.forEach(item => this.add(item));
      this.input.value = '';
    });
  }

  add(value) {
    if (!value || this.chips.includes(value)) return;
    this.chips.push(value);

    const chip = document.createElement('span');
    chip.className = this.type === 'link' ? 'chip chip-link' : 'chip';
    chip.innerHTML = `
      <span class="chip-text">${this._escapeHtml(value)}</span>
      <button type="button" class="chip-remove" aria-label="Remove">&times;</button>
    `;

    chip.querySelector('.chip-remove').addEventListener('click', (e) => {
      e.stopPropagation();
      const idx = this.chips.indexOf(value);
      if (idx > -1) this.removeAt(idx);
    });

    this.wrap.insertBefore(chip, this.input);
    this._updateCount();
    this.onChange(this.chips);
  }

  removeAt(index) {
    this.chips.splice(index, 1);
    const chipEls = this.wrap.querySelectorAll('.chip');
    if (chipEls[index]) {
      chipEls[index].style.animation = 'none';
      chipEls[index].style.transition = 'opacity 0.15s, transform 0.15s';
      chipEls[index].style.opacity = '0';
      chipEls[index].style.transform = 'scale(0.8)';
      setTimeout(() => chipEls[index].remove(), 150);
    }
    this._updateCount();
    this.onChange(this.chips);
  }

  setValues(values) {
    this.clear();
    (values || []).forEach(v => this.add(v));
  }

  getValues() { return [...this.chips]; }

  clear() {
    this.chips = [];
    this.wrap.querySelectorAll('.chip').forEach(el => el.remove());
    this._updateCount();
  }

  _updateCount() {
    const n = this.chips.length;
    this.countEl.textContent = n ? `${n} item${n !== 1 ? 's' : ''}` : '';
  }

  _escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
}

// ═══════════════════════════════════════════════════════════════════
// SearchDropdown — searchable dropdown with presets + freetext
// ═══════════════════════════════════════════════════════════════════
class SearchDropdown {
  /**
   * @param {HTMLElement} container
   * @param {Object} opts
   * @param {string[]} opts.options — preset options
   * @param {string} opts.placeholder
   * @param {boolean} opts.allowCustom — allow typing custom values
   * @param {Function} opts.onChange — called with selected value
   */
  constructor(container, opts = {}) {
    this.container = container;
    this.options = opts.options || [];
    this.placeholder = opts.placeholder || 'Select...';
    this.allowCustom = opts.allowCustom !== false;
    this.onChange = opts.onChange || (() => {});
    this.value = '';
    this.isOpen = false;
    this.highlightedIndex = -1;

    this._build();
    this._bindEvents();
  }

  _build() {
    // Trigger button
    this.trigger = document.createElement('button');
    this.trigger.type = 'button';
    this.trigger.className = 'dropdown-trigger';
    this.trigger.innerHTML = `
      <span class="dropdown-value placeholder">${this.placeholder}</span>
      <svg class="dropdown-arrow" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
        <path d="M4 6l4 4 4-4"/>
      </svg>
    `;

    // Panel
    this.panel = document.createElement('div');
    this.panel.className = 'dropdown-panel';

    this.searchInput = document.createElement('input');
    this.searchInput.type = 'text';
    this.searchInput.className = 'dropdown-search';
    this.searchInput.placeholder = this.allowCustom ? 'Search or type custom...' : 'Search...';

    this.optionsContainer = document.createElement('div');
    this.optionsContainer.className = 'dropdown-options';

    this.panel.appendChild(this.searchInput);
    this.panel.appendChild(this.optionsContainer);

    const wrap = document.createElement('div');
    wrap.className = 'dropdown-wrap';
    wrap.appendChild(this.trigger);
    wrap.appendChild(this.panel);
    this.container.appendChild(wrap);

    this._renderOptions('');
  }

  _bindEvents() {
    this.trigger.addEventListener('click', () => this.isOpen ? this.close() : this.open());

    this.searchInput.addEventListener('input', () => {
      this._renderOptions(this.searchInput.value.trim().toLowerCase());
    });

    this.searchInput.addEventListener('keydown', (e) => {
      const visible = this.optionsContainer.querySelectorAll('.dropdown-option');
      if (e.key === 'ArrowDown') {
        e.preventDefault();
        this.highlightedIndex = Math.min(this.highlightedIndex + 1, visible.length - 1);
        this._updateHighlight(visible);
      } else if (e.key === 'ArrowUp') {
        e.preventDefault();
        this.highlightedIndex = Math.max(this.highlightedIndex - 1, 0);
        this._updateHighlight(visible);
      } else if (e.key === 'Enter') {
        e.preventDefault();
        if (this.highlightedIndex >= 0 && visible[this.highlightedIndex]) {
          this.select(visible[this.highlightedIndex].textContent);
        } else if (this.allowCustom && this.searchInput.value.trim()) {
          this.select(this.searchInput.value.trim());
        }
      } else if (e.key === 'Escape') {
        this.close();
      }
    });

    document.addEventListener('click', (e) => {
      if (!this.container.contains(e.target)) this.close();
    });
  }

  _renderOptions(filter) {
    const filtered = this.options.filter(o => o.toLowerCase().includes(filter));
    this.highlightedIndex = -1;

    if (filtered.length === 0 && !this.allowCustom) {
      this.optionsContainer.innerHTML = '<div class="dropdown-empty">No matches</div>';
      return;
    }

    this.optionsContainer.innerHTML = '';
    filtered.forEach(opt => {
      const btn = document.createElement('button');
      btn.type = 'button';
      btn.className = 'dropdown-option' + (opt === this.value ? ' selected' : '');
      btn.textContent = opt;
      btn.addEventListener('click', () => this.select(opt));
      this.optionsContainer.appendChild(btn);
    });

    if (this.allowCustom && filter && !filtered.includes(filter)) {
      const custom = document.createElement('button');
      custom.type = 'button';
      custom.className = 'dropdown-option';
      custom.innerHTML = `Use "<strong>${this._escapeHtml(filter)}</strong>"`;
      custom.addEventListener('click', () => this.select(filter));
      this.optionsContainer.appendChild(custom);
    }
  }

  _updateHighlight(visible) {
    visible.forEach((el, i) => el.classList.toggle('highlighted', i === this.highlightedIndex));
    if (visible[this.highlightedIndex]) {
      visible[this.highlightedIndex].scrollIntoView({ block: 'nearest' });
    }
  }

  open() {
    this.isOpen = true;
    this.trigger.classList.add('open');
    this.panel.classList.add('open');
    this.searchInput.value = '';
    this._renderOptions('');
    setTimeout(() => this.searchInput.focus(), 50);
  }

  close() {
    this.isOpen = false;
    this.trigger.classList.remove('open');
    this.panel.classList.remove('open');
    this.trigger.focus();
  }

  select(val) {
    this.value = val;
    this.trigger.querySelector('.dropdown-value').textContent = val;
    this.trigger.querySelector('.dropdown-value').classList.remove('placeholder');
    this.close();
    this.onChange(val);
  }

  setValue(val) {
    if (!val) return;
    this.value = val;
    this.trigger.querySelector('.dropdown-value').textContent = val;
    this.trigger.querySelector('.dropdown-value').classList.remove('placeholder');
  }

  getValue() { return this.value; }

  _escapeHtml(str) {
    const d = document.createElement('div');
    d.textContent = str;
    return d.innerHTML;
  }
}

// ═══════════════════════════════════════════════════════════════════
// Sidebar injection — persistent sidebar for app pages
// ═══════════════════════════════════════════════════════════════════

const _SIDEBAR_NAV_ICONS = {
  dashboard: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="2" width="5.5" height="5.5" rx="1.5"/><rect x="10.5" y="2" width="5.5" height="5.5" rx="1.5"/><rect x="2" y="10.5" width="5.5" height="5.5" rx="1.5"/><rect x="10.5" y="10.5" width="5.5" height="5.5" rx="1.5"/></svg>`,
  workspace: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M9 2l6 3.5v7L9 16l-6-3.5v-7z"/><path d="M9 8.5v7.5"/><path d="M3 5.5L9 9l6-3.5"/></svg>`,
  settings: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><line x1="3" y1="5" x2="15" y2="5"/><line x1="3" y1="9" x2="15" y2="9"/><line x1="3" y1="13" x2="15" y2="13"/><circle cx="6.5" cy="5" r="1.5" fill="currentColor" stroke="none"/><circle cx="11.5" cy="9" r="1.5" fill="currentColor" stroke="none"/><circle cx="8" cy="13" r="1.5" fill="currentColor" stroke="none"/></svg>`,
  account: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="6.5" r="3"/><path d="M3 16.5c0-3 2.7-5.5 6-5.5s6 2.5 6 5.5"/></svg>`,
  logout: `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 15H4.5a1.5 1.5 0 01-1.5-1.5v-9A1.5 1.5 0 014.5 3h2"/><path d="M12 12.5l3-3.5-3-3.5"/><line x1="7" y1="9" x2="15" y2="9"/></svg>`,
};

const _SIDEBAR_PIN_ICON = `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="2.5" y="3.5" width="13" height="11" rx="2"/><line x1="7.5" y1="3.5" x2="7.5" y2="14.5"/></svg>`;
const _SIDEBAR_UNPIN_ICON = _SIDEBAR_PIN_ICON;

function injectSidebar(opts = {}) {
  const target = document.getElementById('rm-sidebar-slot');
  if (!target) return;

  const active = opts.activePage || '';
  const navItems = [
    { key: 'dashboard', label: 'Dashboard', href: '/' },
    { key: 'workspace', label: 'Workspace', href: '/workspace' },
    { key: 'settings',  label: 'Settings',  href: '/settings' },
  ];

  const navHtml = navItems.map(n =>
    `<a href="${n.href}" class="sb-nav-item${active === n.key ? ' active' : ''}" data-tooltip="${n.label}">${_SIDEBAR_NAV_ICONS[n.key]}<span>${n.label}</span></a>`
  ).join('');

  target.outerHTML = `
    <aside class="sidebar collapsed">
      <div class="sb-header">
        <a href="/" class="sb-logo">Resu<b>Mate</b></a>
        <button class="sb-collapse-btn" id="sb-pin-btn" title="Pin sidebar open">${_SIDEBAR_UNPIN_ICON}</button>
      </div>
      <div class="sb-section-label">Menu</div>
      <nav class="sb-nav">${navHtml}</nav>
      <div class="sb-spacer"></div>
      <div class="sb-profile" id="sb-profile">
        <button class="sb-profile-card" id="sb-profile-toggle" aria-expanded="false" aria-controls="sb-profile-menu" data-tooltip="Account">
          <span class="sb-profile-avatar" id="sb-profile-avatar">${_AVATAR_FALLBACK_SVG}</span>
          <span class="sb-profile-text">
            <span class="sb-profile-name" id="sb-profile-name">Account</span>
            <span class="sb-profile-email" id="sb-profile-email">—</span>
          </span>
          <svg class="sb-profile-caret" width="14" height="14" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M4 6l4 4 4-4"/></svg>
        </button>
        <div class="sb-profile-menu" id="sb-profile-menu">
          <a href="/settings" class="sb-profile-item">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="8" cy="8" r="2.2"/><path d="M8 1.5v2M8 12.5v2M1.5 8h2M12.5 8h2M3.4 3.4l1.4 1.4M11.2 11.2l1.4 1.4M3.4 12.6l1.4-1.4M11.2 4.8l1.4-1.4"/></svg>
            <span>Settings</span>
          </a>
          <button type="button" class="sb-profile-item danger" id="sb-logout">
            <svg width="15" height="15" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M10 4V2.5A1.5 1.5 0 0 0 8.5 1h-5A1.5 1.5 0 0 0 2 2.5v11A1.5 1.5 0 0 0 3.5 15h5A1.5 1.5 0 0 0 10 13.5V12"/><path d="M13 8H6M11 5l3 3-3 3"/></svg>
            <span>Logout</span>
          </button>
        </div>
      </div>
    </aside>
  `;

  // Sidebar: auto-hide (collapsed by default), expand on hover, pin to lock open
  const sidebar = document.querySelector('.sidebar');
  const pinBtn = document.getElementById('sb-pin-btn');
  let _sidebarPinned = localStorage.getItem('rm_sidebar_pinned') === '1';

  // If pinned, start expanded
  if (_sidebarPinned) {
    sidebar.classList.remove('collapsed');
    pinBtn.innerHTML = _SIDEBAR_PIN_ICON;
    pinBtn.title = 'Unpin sidebar';
  }

  // Hover expand/collapse (only when not pinned)
  sidebar.addEventListener('mouseenter', () => {
    if (!_sidebarPinned) sidebar.classList.remove('collapsed');
  });
  sidebar.addEventListener('mouseleave', () => {
    if (!_sidebarPinned) sidebar.classList.add('collapsed');
  });

  // Pin toggle
  pinBtn.addEventListener('click', () => {
    _sidebarPinned = !_sidebarPinned;
    localStorage.setItem('rm_sidebar_pinned', _sidebarPinned ? '1' : '0');
    if (_sidebarPinned) {
      sidebar.classList.remove('collapsed');
      pinBtn.innerHTML = _SIDEBAR_PIN_ICON;
      pinBtn.title = 'Unpin sidebar';
    } else {
      sidebar.classList.add('collapsed');
      pinBtn.innerHTML = _SIDEBAR_UNPIN_ICON;
      pinBtn.title = 'Pin sidebar open';
    }
  });

  // Add app-page class to html/body for overflow control
  document.documentElement.classList.add('app-page');
  document.body.classList.add('app-page');

  // ── Sidebar profile block ───────────────────────────────────────
  const profileToggle = document.getElementById('sb-profile-toggle');
  const profileMenu = document.getElementById('sb-profile-menu');
  const logoutBtn = document.getElementById('sb-logout');
  if (profileToggle && profileMenu) {
    profileToggle.addEventListener('click', (e) => {
      e.stopPropagation();
      const open = profileMenu.classList.toggle('open');
      profileToggle.setAttribute('aria-expanded', open ? 'true' : 'false');
    });
    document.addEventListener('click', (e) => {
      if (!profileMenu.contains(e.target) && e.target !== profileToggle) {
        profileMenu.classList.remove('open');
        profileToggle.setAttribute('aria-expanded', 'false');
      }
    });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape') {
        profileMenu.classList.remove('open');
        profileToggle.setAttribute('aria-expanded', 'false');
      }
    });
  }
  if (logoutBtn) {
    logoutBtn.addEventListener('click', () => {
      window.location = '/auth/logout';
    });
  }

  // Populate sidebar profile data.
  loadUser().then((user) => {
    if (!user) return;
    const nameEl   = document.getElementById('sb-profile-name');
    const emailEl  = document.getElementById('sb-profile-email');
    const avatarEl = document.getElementById('sb-profile-avatar');
    if (nameEl  && user.name)  nameEl.textContent  = user.name;
    if (emailEl && user.email) emailEl.textContent = user.email;
    if (avatarEl) {
      const initials = (user.name || user.email || '?')
        .split(/\s+/).slice(0, 2).map(s => s[0]).join('').toUpperCase();
      _setAvatar(avatarEl, user.picture, initials);
    }
  });

  // Dashboard greeting (no-op on pages without #greeting-text)
  initTopbar();
}

// ── Profile completion — shared logic ─────────────────────────────
async function getProfileCompletion() {
  try {
    const res = await apiFetch('/profile');
    if (!res || !res.ok) return null;
    const data = await res.json();
    const checks = [
      { key: 'name', done: !!data.name },
      { key: 'email', done: !!data.email },
      { key: 'title', done: !!data.title },
      { key: 'location', done: !!data.location },
      { key: 'phone', done: !!data.phone },
      { key: 'target_role', done: !!data.target_role },
      { key: 'skills', done: !!(data.skills && data.skills.length) },
      { key: 'pitch', done: !!data.pitch },
      { key: 'achievements', done: !!(data.achievements && data.achievements.length) },
      { key: 'links', done: !!(data.links && data.links.length) },
      { key: 'role_keywords', done: !!(data.role_keywords && data.role_keywords.length) },
      { key: 'domain_focus', done: !!data.domain_focus },
      { key: 'persona_tone', done: !!data.persona_tone },
    ];
    const done = checks.filter(c => c.done).length;
    const pct = Math.round((done / checks.length) * 100);
    return { checks, done, total: checks.length, pct };
  } catch (_) { return null; }
}

// Legacy wrapper — used by dashboard index.html
async function initProfileWidget() {
  const completion = await getProfileCompletion();
  if (!completion) return;

  const widget = document.getElementById('profile-widget');
  if (!widget) return;
  widget.style.display = '';

  const circumference = 2 * Math.PI * 15;
  const offset = circumference * (1 - completion.pct / 100);
  const ringFill = document.getElementById('ring-fill');
  const ringPct = document.getElementById('ring-pct');
  if (ringFill) ringFill.setAttribute('stroke-dashoffset', offset);
  if (ringPct) ringPct.textContent = completion.pct + '%';

  if (completion.pct >= 100) {
    const pwLabel = document.getElementById('pw-label');
    const pwSub = document.getElementById('pw-sub');
    const pwLink = document.getElementById('pw-link');
    if (pwLabel) pwLabel.textContent = 'Profile complete';
    if (pwSub) pwSub.textContent = 'ready to generate';
    if (ringFill) ringFill.setAttribute('stroke', '#16a34a');
    if (pwLink) pwLink.textContent = 'View Settings';
  } else {
    const pwSub = document.getElementById('pw-sub');
    if (pwSub) pwSub.textContent = `${completion.done} of ${completion.total} fields`;
  }
}

// ── Topbar greeting (dashboard only) ────────────────────────────
// The sidebar profile card is the only account menu; the topbar just greets.
async function initTopbar() {
  const greetingEl = document.getElementById('greeting-text');
  if (!greetingEl) return;
  const user = await loadUser();
  const firstName = ((user && (user.name || user.email)) || '').split(' ')[0];
  const h = new Date().getHours();
  const timeGreeting = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
  greetingEl.textContent = firstName ? `${timeGreeting}, ${firstName}` : timeGreeting;
}

// ═══════════════════════════════════════════════════════════════════
// Email parser — extract structured emails from LLM output
// ═══════════════════════════════════════════════════════════════════

function parseEmails(raw) {
  const types = { 1: 'Application', 2: 'Cold Outreach', 3: 'Follow-up' };
  const blocks = raw.split(/\**={2,}\s*Email\s*(\d+)\s*(?::[^=\n]*)?={2,}\**/i).slice(1);
  const clean = (t) => t.replace(/\*\*/g, '').trim();
  const emails = [];
  for (let i = 0; i < blocks.length; i += 2) {
    const num = parseInt(blocks[i]);
    const text = (blocks[i + 1] || '').trim();
    const subjectMatch = text.match(/^\W*Subject:\W*\s*(.+)/im);
    // Body is everything after "Body:", or — when the model omits that label —
    // everything after the Subject line.
    const bodyMatch = text.match(/Body:\**\s*\n?([\s\S]*)/im)
      || (subjectMatch ? [null, text.slice(subjectMatch.index + subjectMatch[0].length)] : null);
    emails.push({
      index: num,
      type: types[num] || `Email ${num}`,
      typeClass: num === 2 ? 'outreach' : num === 3 ? 'followup' : '',
      subject: subjectMatch ? clean(subjectMatch[1]) : '',
      body: clean(bodyMatch ? bodyMatch[1] : text),
    });
  }
  return emails;
}

// Inverse of parseEmails — keeps the raw text (export / auto-save source of
// truth) in sync when emails are edited in the workspace.
function serializeEmails(emails) {
  const types = { 1: 'Application', 2: 'Cold Outreach', 3: 'Follow-up' };
  return emails
    .filter(e => e && (e.subject || e.body))
    .map(e => `=== Email ${e.index}: ${types[e.index] || 'Email'} ===\nSubject: ${e.subject}\nBody:\n${e.body}`)
    .join('\n\n');
}

// ═══════════════════════════════════════════════════════════════════
// Minimal markdown renderer (headings, bold, bullets, numbered lists, rules)
// Escapes HTML first, so model output can never inject markup.
// ═══════════════════════════════════════════════════════════════════
function renderMarkdown(raw) {
  const esc = (t) => t.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
  const inline = (t) => esc(t)
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    // [add metric], [Company Name] … → highlighted fill-in fields
    .replace(/\[([^\]\n]{2,40})\]/g, '<mark class="md-ph">[$1]</mark>')
    .replace(/`([^`]+)`/g, '<code>$1</code>');
  const out = [];
  let list = null;      // 'ul' | 'ol'
  let para = [];
  const flushPara = () => { if (para.length) { out.push('<p>' + para.join('<br>') + '</p>'); para = []; } };
  const closeList = () => { if (list) { out.push('</' + list + '>'); list = null; } };
  for (const line of String(raw || '').split('\n')) {
    const t = line.trim();
    let m;
    if (!t) { flushPara(); closeList(); continue; }
    if (/^(-{3,}|─{3,}|={3,})$/.test(t)) { flushPara(); closeList(); out.push('<hr>'); continue; }
    if ((m = t.match(/^(#{1,4})\s+(.*)$/))) {
      flushPara(); closeList();
      const lvl = Math.min(m[1].length + 1, 4);
      out.push('<h' + lvl + '>' + inline(m[2]) + '</h' + lvl + '>'); continue;
    }
    if ((m = t.match(/^[-*•]\s+(.*)$/))) {
      flushPara();
      if (list !== 'ul') { closeList(); out.push('<ul>'); list = 'ul'; }
      out.push('<li>' + inline(m[1]) + '</li>'); continue;
    }
    if ((m = t.match(/^\d+[.)]\s+(.*)$/))) {
      flushPara();
      if (list !== 'ol') { closeList(); out.push('<ol>'); list = 'ol'; }
      out.push('<li>' + inline(m[1]) + '</li>'); continue;
    }
    closeList();
    para.push(inline(t));
  }
  flushPara(); closeList();
  return out.join('');
}

// ── Auto-init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  const headerSlot = document.getElementById('rm-header-slot');
  if (headerSlot && !headerSlot.childElementCount) injectHeader({ nav: [] });
  const footerSlot = document.getElementById('rm-footer-slot');
  if (footerSlot && !footerSlot.childElementCount) injectFooter();
  // Fallback fade-in for non-View-Transition browsers
  const main = document.querySelector('.main');
  if (main) main.classList.add('fade-in');
});
