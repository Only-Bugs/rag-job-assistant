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
          <a href="/settings">Profile Settings</a>
          <a href="/account">Account</a>
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

const _SIDEBAR_PIN_ICON = `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M11 4L7 9l4 5"/></svg>`;
const _SIDEBAR_UNPIN_ICON = `<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M7 4l4 5-4 5"/></svg>`;

function injectSidebar(opts = {}) {
  const target = document.getElementById('rm-sidebar-slot');
  if (!target) return;

  const active = opts.activePage || '';
  const navItems = [
    { key: 'dashboard', label: 'Dashboard', href: '/' },
    { key: 'workspace', label: 'Workspace', href: '/workspace' },
    { key: 'settings', label: 'Settings', href: '/settings' },
    { key: 'account', label: 'Account', href: '/account' },
  ];

  const navHtml = navItems.map(n =>
    `<a href="${n.href}" class="sb-nav-item${active === n.key ? ' active' : ''}">${_SIDEBAR_NAV_ICONS[n.key]}<span>${n.label}</span></a>`
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

  // Load topbar avatar + dropdown
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

// ── Topbar user init (greeting + avatar + dropdown) ─────────────
const _TOPBAR_DROPDOWN_ICONS = {
  settings: `<svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"><circle cx="9" cy="9" r="2.5"/><path d="M14.7 11.1a1.2 1.2 0 00.24 1.32l.04.04a1.45 1.45 0 11-2.06 2.06l-.04-.04a1.2 1.2 0 00-1.32-.24 1.2 1.2 0 00-.73 1.1v.11a1.45 1.45 0 11-2.9 0v-.06a1.2 1.2 0 00-.79-1.1 1.2 1.2 0 00-1.32.24l-.04.04a1.45 1.45 0 11-2.06-2.06l.04-.04a1.2 1.2 0 00.24-1.32 1.2 1.2 0 00-1.1-.73h-.11a1.45 1.45 0 110-2.9h.06a1.2 1.2 0 001.1-.79 1.2 1.2 0 00-.24-1.32l-.04-.04A1.45 1.45 0 115.42 3.3l.04.04a1.2 1.2 0 001.32.24h.06a1.2 1.2 0 00.73-1.1v-.11a1.45 1.45 0 012.9 0v.06a1.2 1.2 0 00.73 1.1 1.2 1.2 0 001.32-.24l.04-.04a1.45 1.45 0 112.06 2.06l-.04.04a1.2 1.2 0 00-.24 1.32v.06a1.2 1.2 0 001.1.73h.11a1.45 1.45 0 010 2.9h-.06a1.2 1.2 0 00-1.1.73z"/></svg>`,
  account: `<svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><circle cx="9" cy="6.5" r="3"/><path d="M3 16.5c0-3 2.7-5.5 6-5.5s6 2.5 6 5.5"/></svg>`,
  logout: `<svg width="16" height="16" viewBox="0 0 18 18" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M6.5 15H4.5a1.5 1.5 0 01-1.5-1.5v-9A1.5 1.5 0 014.5 3h2"/><path d="M12 12.5l3-3.5-3-3.5"/><line x1="7" y1="9" x2="15" y2="9"/></svg>`,
};

async function initTopbar() {
  const user = await loadUser();
  if (!user) return;

  const name = user.name || user.email || '';
  const firstName = name.split(' ')[0] || '';

  // Greeting
  const greetingEl = document.getElementById('greeting-text');
  if (greetingEl && firstName) {
    const h = new Date().getHours();
    const timeGreeting = h < 12 ? 'Good morning' : h < 17 ? 'Good afternoon' : 'Good evening';
    greetingEl.textContent = `${timeGreeting}, ${firstName}`;
  }

  // Avatar + dropdown
  const avatar = document.getElementById('topbar-avatar');
  if (!avatar) return;

  const initials = name ? name.split(' ').map(w => w[0]).join('').slice(0, 2).toUpperCase() : '';
  _setAvatar(avatar, user.picture, initials);
  avatar.style.display = '';

  // Prevent default link behavior — avatar becomes a dropdown trigger
  avatar.removeAttribute('href');
  avatar.style.cursor = 'pointer';

  // Inject dropdown
  const wrapper = document.createElement('div');
  wrapper.className = 'topbar-avatar-wrap';
  avatar.parentNode.insertBefore(wrapper, avatar);
  wrapper.appendChild(avatar);

  const dd = document.createElement('div');
  dd.className = 'topbar-dropdown';
  dd.innerHTML = `
    <div class="topbar-dd-header">
      <div class="topbar-dd-name">${name}</div>
      <div class="topbar-dd-email">${user.email || ''}</div>
    </div>
    <div class="topbar-dd-divider"></div>
    <a href="/settings" class="topbar-dd-item">${_TOPBAR_DROPDOWN_ICONS.settings}<span>Settings</span></a>
    <a href="/account" class="topbar-dd-item">${_TOPBAR_DROPDOWN_ICONS.account}<span>Account</span></a>
    <div class="topbar-dd-divider"></div>
    <a href="/auth/logout" class="topbar-dd-item topbar-dd-danger">${_TOPBAR_DROPDOWN_ICONS.logout}<span>Sign Out</span></a>
  `;
  wrapper.appendChild(dd);

  // Toggle
  avatar.addEventListener('click', (e) => {
    e.preventDefault();
    e.stopPropagation();
    dd.classList.toggle('open');
  });
  document.addEventListener('click', () => dd.classList.remove('open'));
  dd.addEventListener('click', (e) => e.stopPropagation());
}

// ═══════════════════════════════════════════════════════════════════
// Email parser — extract structured emails from LLM output
// ═══════════════════════════════════════════════════════════════════

function parseEmails(raw) {
  const types = { 1: 'Application', 2: 'Outreach', 3: 'Follow-up' };
  const blocks = raw.split(/===\s*Email\s*(\d+)\s*===/i).slice(1);
  const emails = [];
  for (let i = 0; i < blocks.length; i += 2) {
    const num = parseInt(blocks[i]);
    const text = (blocks[i + 1] || '').trim();
    const subjectMatch = text.match(/^Subject:\s*(.+)/im);
    const bodyMatch = text.match(/Body:\s*\n?([\s\S]*)/im);
    emails.push({
      index: num,
      type: types[num] || `Email ${num}`,
      typeClass: num === 2 ? 'outreach' : num === 3 ? 'followup' : '',
      subject: subjectMatch ? subjectMatch[1].trim() : '',
      body: bodyMatch ? bodyMatch[1].trim() : text,
    });
  }
  return emails;
}

// ── Auto-init ───────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  if (document.getElementById('rm-header-slot')) {
    injectHeader({ nav: [] });
  }
  if (document.getElementById('rm-footer-slot')) {
    injectFooter();
  }
  // Fallback fade-in for non-View-Transition browsers
  const main = document.querySelector('.main');
  if (main) main.classList.add('fade-in');
});
