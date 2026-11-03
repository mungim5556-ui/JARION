"use client";

import { useRouter } from "next/navigation";
import { createContext, useContext, useEffect, useState } from "react";
import { api, ApiError, type User } from "@/lib/api";

const UserContext = createContext<User | null>(null);
export const useUser = () => useContext(UserContext)!;

/** 로그인 확인 + 상단 바. 로그인 안 되어 있으면 /login 으로 보낸다. */
export default function Shell({ children, adminOnly = false }: { children: React.ReactNode; adminOnly?: boolean }) {
  const router = useRouter();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    api<User>("/api/auth/me")
      .then((u) => {
        if (adminOnly && u.role !== "admin") router.replace("/");
        else setUser(u);
      })
      .catch((e) => {
        if (e instanceof ApiError && e.status === 401) router.replace("/login/");
      });
  }, [adminOnly, router]);

  async function logout() {
    await api("/api/auth/logout", { method: "POST" }).catch(() => {});
    router.replace("/login/");
  }

  if (!user) return null;

  return (
    <UserContext.Provider value={user}>
      <header className="header">
        <div className="container">
          <a className="brand" href="/">
            JARION<small>원격 실습실</small>
          </a>
          <div className="spacer" />
          {user.role === "admin" && (adminOnly ? <a href="/">학생 화면</a> : <a href="/admin/">관리</a>)}
          <span className="who">{user.display_name || user.username}</span>
          <button className="btn sm" onClick={logout}>
            로그아웃
          </button>
        </div>
      </header>
      <main>
        <div className="container">{children}</div>
      </main>
    </UserContext.Provider>
  );
}
