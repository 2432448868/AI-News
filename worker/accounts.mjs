// One strongly consistent Durable Object per GitHub numeric user ID.
// SQLite-backed storage is accessed through the KV API; no handwritten SQL.
const MAX_FAVORITES = 200;
const MAX_TAGS = 30;
const MAX_SESSIONS = 8;
const SESSION_MS = 7 * 24 * 3600000;
export const SESSION_SECONDS = SESSION_MS / 1000;

export class UserAccount {
  constructor(ctx) {
    this.ctx = ctx;
  }
  async fetch(request) {
    const command = await request.json();
    const result = await this.ctx.storage.transaction(async (store) => {
      const now = Date.now();
      const data = (await store.get('account')) || {
        profile: null,
        favorites: [],
        tags: [],
        sessions: [],
      };
      data.sessions = data.sessions.filter((s) => s.expiresAt > now);
      if (command.action === 'login') {
        const { id, login, name } = command.profile;
        if (data.profile && data.profile.id !== id)
          return { status: 403, error: 'Account mismatch' };
        data.profile = { id, login, displayName: data.profile?.displayName || name || login };
        data.sessions.push({
          hash: command.hash,
          csrf: command.csrf,
          expiresAt: now + SESSION_MS,
          windowStart: now,
          writes: 0,
        });
        data.sessions = data.sessions.slice(-MAX_SESSIONS);
        await store.put('account', data);
        return { status: 200 };
      }
      const session = data.sessions.find((s) => s.hash === command.hash);
      if (!session || !data.profile) return { status: 401, error: '请重新登录。' };
      const view = () => ({
        status: 200,
        available: true,
        user: data.profile,
        favorites: data.favorites,
        tags: data.tags,
        csrf: session.csrf,
      });
      if (command.action === 'read') return view();
      if (command.csrf !== session.csrf)
        return { status: 403, error: '安全校验失败，请刷新后重试。' };
      if (command.action === 'logout') {
        data.sessions = data.sessions.filter((s) => s.hash !== command.hash);
        await store.put('account', data);
        return { status: 200 };
      }
      if (now - session.windowStart >= 60000) {
        session.windowStart = now;
        session.writes = 0;
      }
      if (session.writes >= 30) return { status: 429, error: '操作太频繁，请稍后重试。' };
      switch (command.action) {
        case 'profile': {
          const name = command.body.displayName;
          if (
            typeof name !== 'string' ||
            !name.trim() ||
            name.trim().length > 60 ||
            /[\u0000-\u001f\u007f]/.test(name)
          )
            return { status: 400, error: '昵称需为 1–60 个字符。' };
          data.profile.displayName = name.trim();
          break;
        }
        case 'favorite': {
          const { id, saved } = command.body;
          if (typeof id !== 'string' || !id || id.length > 200 || typeof saved !== 'boolean')
            return { status: 400, error: '收藏参数无效。' };
          if (saved && !data.favorites.includes(id)) {
            if (data.favorites.length >= MAX_FAVORITES)
              return { status: 409, error: '最多收藏 200 条资讯。' };
            data.favorites.push(id);
          } else if (!saved) data.favorites = data.favorites.filter((value) => value !== id);
          break;
        }
        case 'tag': {
          const { tag, followed } = command.body;
          if (
            typeof tag !== 'string' ||
            !tag.trim() ||
            tag.trim().length > 40 ||
            /[\u0000-\u001f\u007f]/.test(tag) ||
            typeof followed !== 'boolean'
          )
            return { status: 400, error: '标签需为 1–40 个字符。' };
          const value = tag.trim();
          if (followed && !data.tags.includes(value)) {
            if (data.tags.length >= MAX_TAGS) return { status: 409, error: '最多关注 30 个标签。' };
            data.tags.push(value);
          } else if (!followed) data.tags = data.tags.filter((item) => item !== value);
          break;
        }
        default:
          return { status: 404, error: 'Not found' };
      }
      session.writes++;
      await store.put('account', data);
      return view();
    });
    return Response.json(result, { status: result.status });
  }
}
