/**
 * Color de texto por franja de la liga de clasificación, según el nombre
 * que entrega la API, por ejemplo "Electro League 32" o "Titan League 27".
 *
 * Son colores propios, elegidos para evocar a la tropa que le da nombre
 * a cada franja; no son códigos oficiales de Supercell, así que son los
 * primeros que valdría la pena ajustar a ojo una vez los veas en pantalla.
 */
const COLOR_POR_FRANJA: Record<string, string> = {
  Unranked: '#9CA3AF',
  Skeleton: '#9CA3AF',
  Barbarian: '#C97B3D',
  Archer: '#4C9A4C',
  Wizard: '#8B5CF6',
  Valkyrie: '#E0529C',
  Witch: '#5B3A8E',
  Golem: '#8D7B68',
  'P.E.K.K.A': '#5B7C99',
  Titan: '#8B2E2E',
  Dragon: '#D9480F',
  Electro: '#22D3EE',
  Legend: '#D4AF37',
}

/**
 * Devuelve el color para el nombre de liga dado. El nombre de la API
 * siempre empieza con el nombre de la franja seguido de un número, así
 * que basta con revisar con cuál de las claves conocidas empieza.
 */
export function colorLiga(nombreLiga: string | null): string {
  if (!nombreLiga) return COLOR_POR_FRANJA.Unranked
  const franja = Object.keys(COLOR_POR_FRANJA).find((clave) => nombreLiga.startsWith(clave))
  return franja ? COLOR_POR_FRANJA[franja] : COLOR_POR_FRANJA.Unranked
}