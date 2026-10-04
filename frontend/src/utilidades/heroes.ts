/**
 * Mapa de calor del nivel de los héroes de la aldea principal, según qué
 * tan al día están respecto al ayuntamiento (TH) del jugador.
 */

export type ClaveHeroe = 'bk' | 'aq' | 'gw' | 'rc' | 'mp' | 'dd'

/** Nivel máximo de cada héroe por ayuntamiento, hasta TH18. */
export const maxHeroesTH: Record<number, Record<ClaveHeroe, number>> = {
  18: { bk: 110, aq: 110, gw: 85, rc: 55, mp: 95, dd: 25 },
  17: { bk: 100, aq: 100, gw: 75, rc: 50, mp: 90, dd: 20 },
  16: { bk: 95, aq: 95, gw: 70, rc: 45, mp: 80, dd: 15 },
  15: { bk: 90, aq: 90, gw: 65, rc: 40, mp: 70, dd: 10 },
  14: { bk: 85, aq: 85, gw: 60, rc: 30, mp: 50, dd: 0 },
  13: { bk: 75, aq: 75, gw: 50, rc: 25, mp: 40, dd: 0 },
  12: { bk: 65, aq: 65, gw: 40, rc: 0, mp: 0, dd: 0 },
  11: { bk: 50, aq: 50, gw: 20, rc: 0, mp: 0, dd: 0 },
  10: { bk: 40, aq: 40, gw: 0, rc: 0, mp: 0, dd: 0 },
  9: { bk: 30, aq: 30, gw: 0, rc: 0, mp: 0, dd: 0 },
  8: { bk: 10, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
  7: { bk: 5, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
  6: { bk: 0, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
  5: { bk: 0, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
  4: { bk: 0, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
  3: { bk: 0, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
  2: { bk: 0, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
  1: { bk: 0, aq: 0, gw: 0, rc: 0, mp: 0, dd: 0 },
}

const TH_MAXIMO = 18

const COLOR_DORADO = '#D4AF37'
const COLOR_VERDE = '#16A34A'
const COLOR_NARANJA = '#EA580C'
const COLOR_ROJO = '#DC2626'

/**
 * Devuelve el color de texto para el nivel de un héroe, o null cuando ese
 * héroe todavía no está desbloqueado a este ayuntamiento, o no hay dato
 * del nivel todavía: en ambos casos el llamador debería mostrar un guion
 * en vez de pintarlo como si estuviera atrasado.
 *
 * - Dorado: el héroe está en el máximo absoluto del juego (el tope de TH18).
 * - Verde: al día con el ayuntamiento actual.
 * - Naranja: un ayuntamiento atrás.
 * - Rojo: dos ayuntamientos atrás o más.
 */
export function colorNivelHeroe(nivel: number | null, th: number, heroe: ClaveHeroe): string | null {
  const maxEnTH = maxHeroesTH[th]?.[heroe] ?? 0
  if (maxEnTH === 0 || nivel === null) return null

  const maxAbsoluto = maxHeroesTH[TH_MAXIMO][heroe]
  const maxThMenos1 = maxHeroesTH[th - 1]?.[heroe] ?? 0
  const maxThMenos2 = maxHeroesTH[th - 2]?.[heroe] ?? 0

  if (nivel >= maxAbsoluto) return COLOR_DORADO
  if (nivel > maxThMenos1) return COLOR_VERDE
  if (nivel > maxThMenos2) return COLOR_NARANJA
  return COLOR_ROJO
}