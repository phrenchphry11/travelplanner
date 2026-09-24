import { UserButton } from "@clerk/clerk-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { useApi, type Me } from "../lib/api";
import { useCardsDialog } from "../lib/useCardsDialog";
import CardsDialog from "./CardsDialog";

export default function TopBar() {
  const cardsDialog = useCardsDialog();
  const api = useApi();
  const [isAdmin, setIsAdmin] = useState(false);

  useEffect(() => {
    api<Me>("/me")
      .then((me) => setIsAdmin(me.is_admin))
      .catch(() => {}); // only decides whether to show the admin link
  }, [api]);

  return (
    <header className="topbar">
      <Link to="/trips" className="brand">
        Trip Planner
      </Link>
      <span className="topbar-actions">
        {isAdmin && (
          <Link to="/admin" className="small">
            Admin
          </Link>
        )}
        <button type="button" className="link-button small" onClick={cardsDialog.openDialog}>
          Cards & loyalty
        </button>
        <UserButton />
      </span>
      <CardsDialog
        open={cardsDialog.open}
        catalog={cardsDialog.catalog}
        cards={cardsDialog.cards}
        busy={cardsDialog.busy}
        error={cardsDialog.error}
        onSave={cardsDialog.save}
        onClose={cardsDialog.close}
      />
    </header>
  );
}
