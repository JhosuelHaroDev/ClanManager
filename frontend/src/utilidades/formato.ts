/** Fecha y hora legibles en español de Perú, o un guion si no hay dato. */
export function formatearFecha(fecha: string | null): string {
  if (!fecha) return '—'
  return new Date(fecha).toLocaleString('es-PE', { dateStyle: 'medium', timeStyle: 'short' })
}

/** Dos decimales fijos para los porcentajes de destrucción, que la API entrega con muchos más. */
export function formatearPorcentaje(valor: number): string {
  return `${valor.toFixed(2)}%`
}