import { solicitar } from './cliente'

/**
 * Forma de un miembro tal como lo devuelve GET /api/miembros.
 * Refleja a mano el esquema MiembroOut del backend; si ese esquema
 * cambia, este tipo hay que actualizarlo junto con él.
 */
export interface Miembro {
  tag: string
  nombre: string
  rol: string
  nivel_experiencia: number
  nivel_ayuntamiento: number
  trofeos: number
  donaciones: number
  donaciones_recibidas: number
  liga: string | null
  rango_clan: number | null
  rango_clan_anterior: number | null
  trofeos_base: number | null
  liga_base: string | null
}

/**
 * Lista de miembros en vivo, sin niveles de héroe. La pantalla de
 * miembros ya no la usa para la tabla, porque api/capturas.ts trae todo
 * lo mismo más los héroes, pero queda disponible por si otra pantalla
 * necesita el estado más reciente sin pasar por una captura guardada.
 */
export function obtenerMiembros(): Promise<Miembro[]> {
  return solicitar<Miembro[]>('/api/miembros')
}