import { FormEvent, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { Trash2 } from "lucide-react";

import { createAdminUser, deleteAdminUser, fetchAdminUsers, resetAdminUserPassword } from "../api";
import type { AuthUser } from "../types";
import type { UiThemeId } from "../themes";
import { ThemeArtifacts } from "../components/ThemeArtifacts";

export function AdminUsersPage({
  currentUser,
  onClose,
  theme
}: {
  currentUser: AuthUser;
  onClose: () => void;
  theme: UiThemeId;
}) {
  const usersQuery = useQuery({
    queryKey: ["admin-users"],
    queryFn: fetchAdminUsers,
    staleTime: 10_000,
    retry: false
  });
  const [email, setEmail] = useState("");
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [role, setRole] = useState<"admin" | "user">("user");
  const [isCreating, setIsCreating] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");

  async function createUser(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setNotice("");
    setError("");
    const nextEmail = email.trim();
    const nextUsername = username.trim();
    if (!nextEmail) {
      setError("请填写邮箱。");
      return;
    }
    if (nextUsername.length < 2) {
      setError("用户名至少 2 个字符。");
      return;
    }
    if (password.length < 8) {
      setError("初始密码至少 8 个字符。");
      return;
    }
    setIsCreating(true);
    try {
      await createAdminUser({
        email: nextEmail,
        username: nextUsername,
        password,
        role,
        status: "active",
        email_verified: true,
        send_verification: false
      });
      setEmail("");
      setUsername("");
      setPassword("");
      setNotice("用户已创建。");
      await usersQuery.refetch();
    } catch (adminError) {
      setError(adminError instanceof Error ? adminError.message : "创建用户失败。");
    } finally {
      setIsCreating(false);
    }
  }

  async function deleteUser(user: AuthUser) {
    if (user.id === currentUser.id) {
      setError("管理员不能删除自己的账号。");
      return;
    }
    const confirmed = window.confirm(`确定删除 ${user.username} 吗？这也会清理会话和验证码记录。`);
    if (!confirmed) return;
    setNotice("");
    setError("");
    try {
      const result = await deleteAdminUser(user.id);
      setNotice(result.message || "用户已删除。");
      await usersQuery.refetch();
    } catch (adminError) {
      setError(adminError instanceof Error ? adminError.message : "删除用户失败。");
    }
  }

  async function resetPassword(user: AuthUser) {
    const nextPassword = window.prompt(`为 ${user.username} 设置新密码（至少 8 个字符）`);
    if (!nextPassword) return;
    setNotice("");
    setError("");
    try {
      await resetAdminUserPassword(user.id, nextPassword);
      setNotice("密码已重置，现有会话已失效。");
      await usersQuery.refetch();
    } catch (adminError) {
      setError(adminError instanceof Error ? adminError.message : "重置密码失败。");
    }
  }

  return (
    <main className={`adminSurface surfaceTransition theme-${theme}`}>
      <ThemeArtifacts theme={theme} />
      <section className="adminPanel adminPanelStandalone">
        <header>
          <div>
            <p className="eyebrow">管理后台</p>
            <h2>用户管理</h2>
          </div>
          <div className="adminHeaderActions">
            <button type="button" className="pillButton" onClick={onClose}>
              返回
            </button>
          </div>
        </header>
        <form className="adminCreateForm" onSubmit={(event) => void createUser(event)}>
          <input
            placeholder="邮箱"
            type="email"
            autoComplete="email"
            required
            value={email}
            onChange={(event) => setEmail(event.target.value)}
          />
          <input
            placeholder="用户名（至少 2 个字符）"
            autoComplete="username"
            minLength={2}
            maxLength={64}
            required
            value={username}
            onChange={(event) => setUsername(event.target.value)}
          />
          <input
            placeholder="初始密码（至少 8 个字符）"
            type="password"
            autoComplete="new-password"
            minLength={8}
            maxLength={128}
            required
            value={password}
            onChange={(event) => setPassword(event.target.value)}
          />
          <select value={role} onChange={(event) => setRole(event.target.value as "admin" | "user")}>
            <option value="user">普通用户</option>
            <option value="admin">管理员</option>
          </select>
          <button type="submit" className="primaryButton" disabled={isCreating}>
            {isCreating ? "正在创建..." : "创建用户"}
          </button>
        </form>
        <p className="adminFormHint">新用户默认已激活，可用用户名或邮箱直接登录；密码至少 8 个字符。</p>
        {notice ? <p className="authNotice">{notice}</p> : null}
        {error ? <p className="authError">{error}</p> : null}
        <div className="adminUserList">
          {(usersQuery.data?.users ?? []).map((user) => (
            <article key={user.id} className="adminUserRow">
              <div>
                <strong>{user.username}</strong>
                <span>{user.email}</span>
              </div>
              <span>{user.role === "admin" ? "管理员" : "普通用户"}</span>
              <span>{user.status === "disabled" ? "已禁用" : user.email_verified ? "已激活" : "待激活"}</span>
              <div>
                <button type="button" onClick={() => void resetPassword(user)}>
                  重置密码
                </button>
                <button
                  type="button"
                  className="danger"
                  disabled={user.id === currentUser.id}
                  onClick={() => void deleteUser(user)}
                >
                  <Trash2 size={14} />
                  删除
                </button>
              </div>
            </article>
          ))}
        </div>
      </section>
    </main>
  );
}
