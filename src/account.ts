import './account.css';
import { escapeHtml as esc } from './data.mjs';
type User = { id: string; login: string; displayName: string };
type Session = {
  available: boolean;
  user: User | null;
  favorites: string[];
  tags: string[];
  csrf?: string;
};
type Hooks = {
  saved: (ids: string[] | null) => void;
  tag: (value: string) => void;
  toast: (text: string) => void;
};
const element = <T extends HTMLElement>(id: string) => document.getElementById(id) as T;
export function initAccount(hooks: Hooks) {
  const cloud = import.meta.env.VITE_FEED_URL === '/api/feed';
  let state: Session = { available: false, user: null, favorites: [], tags: [] };
  let checking = cloud;
  let failed = false;
  let busy = false;
  const button = element<HTMLButtonElement>('account-button');
  const dialog = element<HTMLDialogElement>('account-dialog');
  const content = element<HTMLDivElement>('account-content');
  const status = element<HTMLParagraphElement>('account-status');
  function render() {
    button.textContent = state.user ? state.user.displayName : '我的账户';
    button.setAttribute(
      'aria-label',
      state.user ? '打开我的账户：' + state.user.displayName : '打开我的账户',
    );
    element('account-caption').textContent = state.user
      ? '你的阅读偏好，随你同行。'
      : '让值得留下的发现，不止留在这台设备。';
    if (checking) {
      content.innerHTML = '<p class="account-note">正在检查登录状态…</p>';
      return;
    }
    if (failed) {
      content.innerHTML =
        '<p class="account-note">暂时无法确认账号状态。为避免混淆本地和云端收藏，恢复连接后再操作。</p><button class="secondary-button" data-account="retry">重新连接</button>';
      return;
    }
    if (!state.user) {
      content.innerHTML =
        '<div class="account-welcome"><span class="account-symbol" aria-hidden="true">S.</span><h3>为好奇心留一个位置</h3><p>云端收藏 · 关注标签 · 跨设备同步</p></div>' +
        (state.available
          ? '<a class="primary-button account-login" href="/api/auth/github">使用 GitHub 登录 <span aria-hidden="true">↗</span></a><p class="account-note">仅使用 GitHub 公开身份，不申请仓库或邮箱权限。登录即创建本站账户。</p>'
          : '<p class="account-note">' +
            (cloud
              ? '管理员尚未启用 GitHub 登录。现在仍可浏览资讯并使用本地收藏。'
              : '当前为 GitHub Pages 静态版，仅提供本地收藏。云端账号功能需在 Cloudflare 版本启用。') +
            '</p>') +
        '<p class="account-privacy">登录后的云端收藏与游客本地收藏分开保存，不会自动上传这台设备上的记录。</p>';
      return;
    }
    content.innerHTML =
      '<div class="account-identity"><span class="account-symbol" aria-hidden="true">' +
      esc(state.user.displayName.slice(0, 1).toUpperCase()) +
      '</span><div><h3>' +
      esc(state.user.displayName) +
      '</h3><p>@' +
      esc(state.user.login) +
      ' · GitHub 已连接</p></div><span class="account-connected">已同步</span></div>' +
      '<div class="account-stats"><div><strong>' +
      state.favorites.length +
      '</strong><span>云端收藏 / 200</span></div><div><strong>' +
      state.tags.length +
      '</strong><span>关注标签 / 30</span></div></div>' +
      '<form id="profile-form" class="account-form"><label for="display-name">显示昵称</label><div class="account-input-row"><input id="display-name" name="displayName" maxlength="60" required value="' +
      esc(state.user.displayName) +
      '" autocomplete="nickname"><button class="secondary-button" type="submit">保存</button></div></form>' +
      '<section class="account-interests" aria-labelledby="interests-title"><h3 id="interests-title">关注标签</h3><p class="account-note">点击标签阅读相关资讯，也可以在资讯区直接关注当前标签。</p><div class="account-tags">' +
      state.tags
        .map(
          (tag) =>
            '<span class="account-tag"><button data-account="explore" data-tag="' +
            esc(tag) +
            '">' +
            esc(tag) +
            '</button><button data-account="unfollow" data-tag="' +
            esc(tag) +
            '" aria-label="取消关注 ' +
            esc(tag) +
            '">×</button></span>',
        )
        .join('') +
      '</div><form id="tag-form" class="account-input-row"><label class="sr-only" for="follow-tag">添加关注标签</label><input id="follow-tag" name="tag" maxlength="40" placeholder="例如 ChatGPT、DeepSeek" required><button class="secondary-button" type="submit">关注</button></form></section>' +
      '<p class="account-privacy">收藏仅在当前资讯快照内展示；旧资讯 ID 会保留，但暂不提供历史全文归档。关注标签用于快速筛选，不发送邮件或通知。</p><button class="text-link account-logout" data-account="logout">退出登录</button>';
    content.querySelectorAll<HTMLButtonElement>('button').forEach((el) => {
      el.disabled = busy;
    });
  }
  async function request(path: string, method = 'GET', body?: unknown): Promise<Session> {
    const response = await fetch(path, {
      method,
      credentials: 'same-origin',
      cache: 'no-store',
      signal: AbortSignal.timeout(15000),
      headers:
        method === 'GET'
          ? {}
          : { 'Content-Type': 'application/json', 'X-CSRF-Token': state.csrf || '' },
      body: body === undefined ? undefined : JSON.stringify(body),
    });
    const result = await response.json();
    if (!response.ok) {
      if (response.status === 401) {
        state = { available: true, user: null, favorites: [], tags: [] };
        hooks.saved(null);
      }
      throw new Error(
        typeof result.error === 'string' ? result.error : '账号请求失败，请稍后重试。',
      );
    }
    return result as Session;
  }
  function apply(next: Session) {
    state = next;
    hooks.saved(next.user ? next.favorites : null);
    render();
  }
  async function refresh() {
    if (!cloud || busy) return;
    checking = true;
    failed = false;
    render();
    try {
      const next = await request('/api/auth/session');
      checking = false;
      apply(next);
    } catch (error) {
      checking = false;
      failed = true;
      status.textContent = error instanceof Error ? error.message : '连接失败。';
      render();
    }
  }
  async function mutate(path: string, body: unknown, message: string) {
    if (busy) {
      hooks.toast('上一项操作尚未完成，请稍等。');
      return;
    }
    busy = true;
    status.textContent = '正在同步…';
    render();
    try {
      apply(await request(path, 'PUT', body));
      status.textContent = message;
      hooks.toast(message);
    } catch (error) {
      status.textContent = error instanceof Error ? error.message : '同步失败，未保存。';
      hooks.toast(status.textContent);
    } finally {
      busy = false;
      render();
    }
  }
  button.addEventListener('click', () => {
    status.textContent = '';
    render();
    dialog.showModal();
    if (cloud && !checking && !busy) void refresh();
  });
  element('account-close').addEventListener('click', () => dialog.close());
  content.addEventListener('submit', (event) => {
    event.preventDefault();
    if (!(event.target instanceof HTMLFormElement)) return;
    const form = new FormData(event.target);
    if (event.target.id === 'profile-form')
      void mutate('/api/user/profile', { displayName: form.get('displayName') }, '昵称已保存。');
    if (event.target.id === 'tag-form')
      void mutate('/api/user/tags', { tag: form.get('tag'), followed: true }, '已关注标签。');
  });
  content.addEventListener('click', async (event) => {
    const target =
      event.target instanceof Element
        ? event.target.closest<HTMLButtonElement>('button[data-account]')
        : null;
    if (!target || busy) return;
    if (target.dataset.account === 'retry') {
      await refresh();
      return;
    }
    if (target.dataset.account === 'explore') {
      dialog.close();
      hooks.tag(target.dataset.tag || '');
      return;
    }
    if (target.dataset.account === 'unfollow') {
      await mutate('/api/user/tags', { tag: target.dataset.tag, followed: false }, '已取消关注。');
      return;
    }
    if (target.dataset.account === 'logout') {
      busy = true;
      render();
      try {
        await request('/api/auth/logout', 'POST');
        apply({ available: true, user: null, favorites: [], tags: [] });
        status.textContent = '已退出，恢复这台设备的本地收藏。';
        hooks.toast(status.textContent);
      } catch (error) {
        status.textContent = error instanceof Error ? error.message : '退出失败，请重试。';
      } finally {
        busy = false;
        render();
      }
    }
  });
  render();
  void refresh();
  const params = new URLSearchParams(location.search);
  if (cloud && params.has('auth')) {
    const success = params.get('auth') === 'success';
    hooks.toast(
      success ? 'GitHub 登录成功，正在加载云端收藏。' : 'GitHub 登录未完成，请重新尝试。',
    );
    params.delete('auth');
    history.replaceState(
      null,
      '',
      location.pathname + (params.size ? '?' + params.toString() : '') + location.hash,
    );
  }
  return {
    save(id: string) {
      if (checking || failed) {
        hooks.toast('请先在账户面板确认连接状态。');
        return true;
      }
      if (!state.user) return false;
      const saved = !state.favorites.includes(id);
      void mutate(
        '/api/user/favorites',
        { id, saved },
        saved ? '已保存到云端收藏。' : '已取消云端收藏。',
      );
      return true;
    },
    follow(tag: string) {
      if (!tag) return;
      if (!state.user || checking || failed) {
        dialog.showModal();
        hooks.toast('登录后可关注标签。');
        return;
      }
      void mutate('/api/user/tags', { tag, followed: true }, '已关注标签，可在账户面板快速阅读。');
    },
  };
}
