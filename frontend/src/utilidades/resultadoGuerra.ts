import type { GuerraResumen } from '../api/guerras'

export type Resultado = 'victoria' | 'derrota' | 'empate' | 'en_curso' | 'preparacion'

export const ETIQUETA_RESULTADO: Record<Resultado, string> = {
  victoria: 'Victoria',
  derrota: 'Derrota',
  empate: 'Empate',
  en_curso: 'En curso',
  preparacion: 'Preparación',
}

export const COLOR_RESULTADO: Record<Resultado, string> = {
  victoria: '#16A34A',
  derrota: '#DC2626',
  empate: '#6B7280',
  en_curso: '#2B7FAE',
  preparacion: '#64748B',
}

/**
 * Resultado de una guerra guardada, siguiendo el mismo criterio de
 * desempate que usa el juego: primero estrellas, y si están empatadas,
 * el porcentaje de destrucción. Antes de que la guerra termine, el
 * resultado todavía no es definitivo, así que se marca aparte, y
 * distinguiendo si sigue en preparación o ya está en batalla.
 *
 * Sirve tanto para guerras clásicas como para rondas de la liga.
 */
export function resultadoDe(
  g: Pick<GuerraResumen, 'estado' | 'clan_estrellas' | 'rival_estrellas' | 'clan_destruccion' | 'rival_destruccion'>,
): Resultado {
  if (g.estado === 'preparation') return 'preparacion'
  if (g.estado !== 'warEnded') return 'en_curso'
  if (g.clan_estrellas !== g.rival_estrellas) {
    return g.clan_estrellas > g.rival_estrellas ? 'victoria' : 'derrota'
  }
  if (g.clan_destruccion !== g.rival_destruccion) {
    return g.clan_destruccion > g.rival_destruccion ? 'victoria' : 'derrota'
  }
  return 'empate'
}