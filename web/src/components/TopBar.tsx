import { UserButton } from "@clerk/clerk-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { useApi, type CardsOut } from "../lib/api";
import CardsDialog from "./CardsDialog";

export default function TopBar() {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<string[]>([]);
  const [cards, setCards] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function openCards() {
    setError(null);
    setOpen(true);
    void Promise.all([
      catalog.length ? Promise.resolve({ catalog }) : api<{ catalog: string[] }>("/cards/catalog"),
      api<CardsOut>("/me/cards"),
    ])
      .then(([c, u]) => {
        setCatalog(c.catalog);
        setCards(u.cards);
      })
      .catch((err) => setError(err instanceof Error ? err.message : String(err)));
  }

  async function saveCards(next: string[]) {
    setBusy(true);
    setError(null);
    try {
      const res = await api<CardsOut>("/me/cards", { method: "PUT", body: JSON.stringify({ cards: next }) });
      setCards(res.cards);
      setOpen(false);
    } finally {
      setBusy(false);
    }
  }

  return (
    <header className="topbar">
      <Link to="/trips" className="brand">
        Trip Planner
      </Link>
      <span className="topbar-actions">
        <button type="button" className="link-button small" onClick={openCards}>
          Cards & loyalty
        </button>
        <UserButton />
      </span>
      <CardsDialog
        open={open}
        catalog={catalog}
        cards={cards}
        busy={busy}
        error={error}
        onSave={saveCards}
        onClose={() => setOpen(false)}
      />
    </header>
  );
}
