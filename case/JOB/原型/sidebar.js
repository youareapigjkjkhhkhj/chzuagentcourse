/* CareerAgent 原型 · 共享侧边栏（body[data-active] 指定当前项） */
(function () {
  var icons = {
    resume: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M6 3h8l4 4v14a1 1 0 0 1-1 1H6a1 1 0 0 1-1-1V4a1 1 0 0 1 1-1Z"/><path d="M14 3v4h4M9 12h6M9 16h6"/></svg>',
    job: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>',
    interview: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3a3 3 0 0 1 3 3v6a3 3 0 0 1-6 0V6a3 3 0 0 1 3-3Z"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3M8.5 21h7"/></svg>',
    profile: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M3 20h18M6 20v-7M11 20V9M16 20v-4M21 20V5"/></svg>',
    agent: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="5" y="5" width="14" height="14" rx="2"/><path d="M9 2v3M15 2v3M9 19v3M15 19v3M2 9h3M2 15h3M19 9h3M19 15h3"/><circle cx="12" cy="12" r="2.5"/></svg>',
    kb: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M4 19V5a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2v14"/><path d="M4 19a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2M9 7h6"/></svg>',
    model: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 2v4M12 18v4M4.9 4.9l2.8 2.8M16.3 16.3l2.8 2.8M2 12h4M18 12h4M4.9 19.1l2.8-2.8M16.3 7.7l2.8-2.8"/><circle cx="12" cy="12" r="3.5"/></svg>',
    settings: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 0 0 .34 1.87l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.7 1.7 0 0 0-1.87-.34 1.7 1.7 0 0 0-1 1.55V21a2 2 0 1 1-4 0v-.09a1.7 1.7 0 0 0-1-1.55 1.7 1.7 0 0 0-1.87.34l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06A1.7 1.7 0 0 0 4.6 15a1.7 1.7 0 0 0-1.55-1H3a2 2 0 1 1 0-4h.09A1.7 1.7 0 0 0 4.6 9a1.7 1.7 0 0 0-.34-1.87l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06A1.7 1.7 0 0 0 9 4.6a1.7 1.7 0 0 0 1-1.55V3a2 2 0 1 1 4 0v.09a1.7 1.7 0 0 0 1 1.51 1.7 1.7 0 0 0 1.87-.34l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06A1.7 1.7 0 0 0 19.4 9c.9.22 1.55.48 1.55 1H21a2 2 0 1 1 0 4h-.09c0-.52-.65-.78-1.51-1Z"/></svg>'
  };

  function item(key, label, sub, href, badge) {
    var active = document.body.dataset.active === key ? ' is-active' : '';
    return '<div class="side-item' + active + '" onclick="location.href=\'' + href + '\'">' +
      icons[key] + '<span class="side-item__text">' + label + '</span>' +
      (badge ? '<span class="badge">' + badge + '</span>' : (sub ? '<span class="side-item__sub">' + sub + '</span>' : '')) + '</div>';
  }

  /* 会话页（chat）高亮当前求职项目，不再单独占导航项 */
  var chatActive = document.body.dataset.active === 'chat' ? ' is-active' : '';

  var html =
    '<div class="side-logo">' +
      '<div class="logo-mark"><svg width="17" height="17" viewBox="0 0 24 24" fill="none"><circle cx="12" cy="12" r="8.5" stroke="#fff" stroke-width="1.8"/><circle cx="12" cy="12" r="4" stroke="#fff" stroke-width="1.8"/><circle cx="12" cy="12" r="1.2" fill="#fff"/></svg></div>' +
      '<div><div class="logo-name">CareerAgent</div><div class="logo-tag">多智能体求职工作站</div></div>' +
    '</div>' +
    '<div class="side-search">' +
      '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="7"/><path d="m21 21-4.3-4.3"/></svg>' +
      '<input placeholder="搜索" />' +
    '</div>' +
    '<div class="side-scroll">' +
      '<div class="side-group"><div class="side-group__title">求职项目</div>' +
        '<div class="side-item' + chatActive + '" onclick="location.href=\'index.html\'">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><rect x="3" y="7" width="18" height="13" rx="2"/><path d="M9 7V5a2 2 0 0 1 2-2h2a2 2 0 0 1 2 2v2"/></svg>' +
          '<span class="side-item__text">Java 后端求职</span>' +
          '<svg class="star" viewBox="0 0 24 24" fill="currentColor"><path d="m12 2 3 6.6 7 .8-5.2 4.8 1.4 7L12 17.7 5.8 21.2l1.4-7L2 9.4l7-.8 3-6.6Z"/></svg>' +
        '</div>' +
        '<div class="side-item" style="padding-left:35px" onclick="location.href=\'index.html\'"><span class="side-item__text">优化简历 · 字节 JD</span></div>' +
        '<div class="side-item" style="padding-left:35px" onclick="location.href=\'interview.html\'"><span class="side-item__text">技术面试 · 缓存专项</span><span class="badge">2</span></div>' +
        '<div class="side-item" onclick="location.href=\'index.html\'">' +
          '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6"><path d="M12 3l1.8 4.7L18.5 9l-4.7 1.8L12 15.5l-1.8-4.7L5.5 9l4.7-1.3L12 3ZM19 15l.9 2.1L22 18l-2.1.9L19 21l-.9-2.1L16 18l2.1-.9L19 15Z"/></svg>' +
          '<span class="side-item__text">AI 工程方向</span><span class="side-item__sub">暂停</span>' +
        '</div>' +
      '</div>' +
      '<div class="side-divider"></div>' +
      '<div class="side-group"><div class="side-group__title">工作台</div>' +
        item('resume', '简历', '4 个版本', 'resume.html') +
        item('job', '岗位', '12 收藏', 'job.html') +
        item('interview', '面试', '5 场', 'interview.html') +
        item('profile', '能力中心', '', 'profile.html') +
      '</div>' +
      '<div class="side-divider"></div>' +
      '<div class="side-group"><div class="side-group__title">系统</div>' +
        item('agent', 'Agent', '', 'agent.html') +
        item('kb', '知识中心', '', 'kb.html') +
        item('model', '模型配置', 'DeepSeek', 'model.html') +
        item('settings', '设置', '', 'settings.html') +
      '</div>' +
    '</div>' +
    '<div class="side-foot">' +
      '<span class="t-avatar" style="background:#0052d9">张</span>' +
      '<div style="flex:1;min-width:0"><div class="u-name">张同学</div><div class="u-meta"><i></i>本地模式 · 数据仅存本机</div></div>' +
    '</div>';

  var aside = document.createElement('aside');
  aside.className = 'sidebar';
  aside.innerHTML = html;
  document.querySelector('.app-body').prepend(aside);

  /* 通用 toast */
  window.toast = function (text) {
    var el = document.getElementById('toast');
    if (!el) {
      el = document.createElement('div');
      el.className = 't-message'; el.id = 'toast';
      document.body.appendChild(el);
    }
    el.textContent = text;
    el.classList.add('is-show');
    clearTimeout(window.__t);
    window.__t = setTimeout(function () { el.classList.remove('is-show'); }, 2400);
  };
})();
