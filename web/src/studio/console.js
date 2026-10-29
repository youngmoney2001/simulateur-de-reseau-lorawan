// Console CLI du navigateur : historique des commandes (logique pure).

export function createHistory(limit = 100) {
  const items = [];
  let cursor = null; // null : hors historique (ligne en cours)
  return {
    push(line) {
      const text = String(line).trim();
      if (text && items[items.length - 1] !== text) {
        items.push(text);
        if (items.length > limit) items.shift();
      }
      cursor = null;
    },
    // Flèche haut : remonte vers les commandes anciennes ; retourne le texte à afficher.
    up(current) {
      if (!items.length) return current;
      cursor = cursor === null ? items.length - 1 : Math.max(0, cursor - 1);
      return items[cursor];
    },
    down(current) {
      if (cursor === null) return current;
      cursor += 1;
      if (cursor >= items.length) {
        cursor = null;
        return "";
      }
      return items[cursor];
    },
    reset() {
      cursor = null;
    },
    size: () => items.length,
  };
}

// Ligne d'invite affichée devant la saisie.
export function promptText(state) {
  return state?.prompt || "";
}
