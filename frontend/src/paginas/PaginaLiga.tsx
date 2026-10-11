import { useEffect, useState } from 'react'
import { ErrorApi } from '../api/cliente'
import { obtenerResumenLiga, sondearLiga, type RondaMiembro, type ResumenLiga } from '../api/liga'
import { BotonRefresco } from '../componentes/BotonRefresco'
import { formatearPorcentaje } from '../utilidades/formato'
import { COLOR_RESULTADO, ETIQUETA_RESULTADO, resultadoDe } from '../utilidades/resultadoGuerra'

/** Una liga estándar tiene ocho clanes y por lo tanto siete rondas. */
const TOTAL_RONDAS = 7
const NUMEROS_DE_RONDA = Array.from({ length: TOTAL_RONDAS }, (_, i) => i + 1)

/** Contenido de la celda de una ronda en la tabla de miembros. */
function CeldaRonda({ ronda }: { ronda: RondaMiembro | undefined }) {
  if (!ronda) return <span className="text-liga-texto/30">·</span>

  switch (ronda.estado) {
    case 'ataco':
      return (
        <span className="font-semibold" title={`${formatearPorcentaje(ronda.destruccion ?? 0)} de destrucción`}>
          {ronda.estrellas}⭐
        </span>
      )
    case 'pendiente':
      return <span title="Todavía puede atacar en esta ronda">⏳</span>
    case 'sin_ataque':
      return (
        <span className="font-bold text-red-700" title="Estaba en la alineación y no atacó">
          ✗
        </span>
      )
    case 'no_alineado':
      return <span className="text-liga-texto/40">—</span>
  }
}

export function PaginaLiga() {
  const [resumen, setResumen] = useState<ResumenLiga | null>(null)
  const [cargando, setCargando] = useState(true)
  const [error, setError] = useState<string | null>(null)

  async function cargar() {
    setCargando(true)
    setError(null)
    try {
      setResumen(await obtenerResumenLiga())
    } catch (err) {
      setError(err instanceof ErrorApi ? err.message : 'No se pudo conectar con el servidor')
    } finally {
      setCargando(false)
    }
  }

  useEffect(() => {
    // oxlint-disable-next-line react/set-state-in-effect
    cargar()
  }, [])

  async function actualizar() {
    await sondearLiga()
    await cargar()
  }

  const rondasPorNumero = new Map((resumen?.rondas ?? []).map((r) => [r.liga_ronda, r]))

  return (
    <section className="space-y-6">
      <div className="flex items-center justify-between gap-4">
        <h2 className="font-display text-xl font-bold">
          Liga de Guerras de Clanes
          {resumen?.temporada && (
            <span className="font-normal text-base-texto/70"> — temporada {resumen.temporada}</span>
          )}
        </h2>
        <BotonRefresco
          seccion="liga"
          alActualizar={actualizar}
          className="border-liga-borde bg-liga-panel text-liga-texto hover:brightness-95"
        />
      </div>

      {error && (
        <p className="rounded-lg border-2 border-red-300 bg-red-50 px-4 py-2 text-red-700">{error}</p>
      )}
      {cargando && <p>Cargando…</p>}

      {!cargando && !error && resumen && resumen.rondas.length === 0 && (
        <div className="rounded-2xl border-4 border-liga-borde bg-liga-fondo p-6 text-liga-texto">
          Todavía no hay ninguna liga guardada. Si tu clan está en una, usa el botón Actualizar para traerla.
        </div>
      )}

      {!cargando && !error && resumen && resumen.rondas.length > 0 && (
        <div className="space-y-6 rounded-2xl border-4 border-liga-borde bg-liga-fondo p-6 text-liga-texto">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
            {NUMEROS_DE_RONDA.map((numero) => {
              const ronda = rondasPorNumero.get(numero)
              if (!ronda) {
                return (
                  <div
                    key={numero}
                    className="rounded-xl border-2 border-dashed border-liga-borde/60 p-3 text-center text-sm opacity-70"
                  >
                    <p className="font-display font-bold">Ronda {numero}</p>
                    <p>Aún sin emparejar</p>
                  </div>
                )
              }
              const resultado = resultadoDe(ronda)
              return (
                <div key={numero} className="rounded-xl border-2 border-liga-borde bg-liga-panel p-3 text-center">
                  <p className="font-display font-bold">Ronda {numero}</p>
                  <p className="truncate text-sm" title={ronda.rival_nombre}>
                    vs {ronda.rival_nombre}
                  </p>
                  <p className="font-semibold">
                    {ronda.clan_estrellas}⭐ — {ronda.rival_estrellas}⭐
                  </p>
                  <span
                    className="mt-1 inline-block rounded-full bg-white/85 px-2 py-0.5 font-display text-xs font-bold"
                    style={{ color: COLOR_RESULTADO[resultado] }}
                  >
                    {ETIQUETA_RESULTADO[resultado].toUpperCase()}
                  </span>
                </div>
              )
            })}
          </div>

          <div className="overflow-x-auto rounded-xl border-2 border-liga-borde bg-liga-panel">
            <table className="w-full text-left">
              <thead className="font-display">
                <tr className="border-b-2 border-liga-borde">
                  <th className="px-3 py-2">N°</th>
                  <th className="px-3 py-2">Nombre</th>
                  <th className="px-3 py-2">Ayunt.</th>
                  {NUMEROS_DE_RONDA.map((numero) => (
                    <th key={numero} className="px-2 py-2 text-center">
                      R{numero}
                    </th>
                  ))}
                  <th className="px-3 py-2">⭐ total</th>
                  <th className="px-3 py-2">Ataques</th>
                  <th className="px-3 py-2">Perdidos</th>
                  <th className="px-3 py-2">Destrucción prom.</th>
                </tr>
              </thead>
              <tbody>
                {resumen.miembros.map((miembro, indice) => {
                  const porRonda = new Map(miembro.rondas.map((r) => [r.ronda, r]))
                  return (
                    <tr
                      key={miembro.tag}
                      className="border-t border-liga-borde/50 transition-colors hover:bg-liga-fondo/50"
                    >
                      <td className="px-3 py-2 opacity-60">{indice + 1}</td>
                      <td className="px-3 py-2 font-semibold">{miembro.nombre}</td>
                      <td className="px-3 py-2">{miembro.nivel_ayuntamiento}</td>
                      {NUMEROS_DE_RONDA.map((numero) => (
                        <td key={numero} className="px-2 py-2 text-center">
                          <CeldaRonda ronda={porRonda.get(numero)} />
                        </td>
                      ))}
                      <td className="px-3 py-2 font-bold">{miembro.estrellas_total}</td>
                      <td className="px-3 py-2">
                        {miembro.ataques_realizados} / {miembro.rondas_alineado}
                      </td>
                      <td
                        className={`px-3 py-2 font-semibold ${miembro.ataques_perdidos > 0 ? 'text-red-700' : ''}`}
                      >
                        {miembro.ataques_perdidos}
                      </td>
                      <td className="px-3 py-2">
                        {miembro.destruccion_promedio !== null ? formatearPorcentaje(miembro.destruccion_promedio) : '—'}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <p className="text-sm">
            ⭐ estrellas obtenidas · ⏳ aún puede atacar · <span className="font-bold text-red-700">✗</span> estaba
            alineado y no atacó · — no estaba en la alineación
          </p>
        </div>
      )}
    </section>
  )
}