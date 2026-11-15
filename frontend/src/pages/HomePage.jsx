import { useAuth } from "../auth/AuthContext";

export default function HomePage() {
  const { user } = useAuth();
  return (
    <>
      <h1>Hello{user.full_name ? `, ${user.full_name}` : ""}</h1>
      <p style={{ color: "var(--text-2)" }}>Your AI operating system is signed in and ready.</p>
      <div className="card">
        <h2>Where to start</h2>
        <p style={{ color: "var(--text-2)", marginTop: 6 }}>Connect your systems, give the AI a goal, approve what it wants to do, and watch how it is doing from the sidebar.</p>
      </div>
    </>
  );
}
