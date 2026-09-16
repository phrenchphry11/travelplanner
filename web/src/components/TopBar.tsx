import { UserButton } from "@clerk/clerk-react";
import { Link } from "react-router-dom";

export default function TopBar() {
  return (
    <header className="topbar">
      <Link to="/trips" className="brand">
        Trip Planner
      </Link>
      <UserButton />
    </header>
  );
}
