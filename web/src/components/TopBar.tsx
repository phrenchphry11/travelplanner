import { UserButton } from "@clerk/clerk-react";
import { Link } from "react-router-dom";
import { useCardsDialog } from "../lib/useCardsDialog";
import CardsDialog from "./CardsDialog";

export default function TopBar() {
  const cardsDialog = useCardsDialog();

  return (
    <header className="topbar">
      <Link to="/trips" className="brand">
        Trip Planner
      </Link>
      <span className="topbar-actions">
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
