import { useState } from "react";
import { useApi, type CardsOut } from "./api";

/** Shared open/fetch/save state for CardsDialog, used from TopBar and the board's first-time nudge. */
export function useCardsDialog() {
  const api = useApi();
  const [open, setOpen] = useState(false);
  const [catalog, setCatalog] = useState<string[]>([]);
  const [cards, setCards] = useState<string[] | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function openDialog() {
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

  async function save(next: string[]) {
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

  return { open, catalog, cards, busy, error, openDialog, save, close: () => setOpen(false) };
}
