import type { RondaMiembro, ResumenLiga } from '../../api/liga'
import { formatearPorcentaje } from '../../utilidades/formato'
import { COLOR_RESULTADO, ETIQUETA_RESULTADO, resultadoDe } from '../../utilidades/resultadoGuerra'

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

/** Resultados de nuestro clan ronda por ronda, y el desempeño de cada miembro a lo largo de la liga. */
export function VistaClan({ resumen }: { resumen: ResumenLiga }) {
  const numeros = Array.from({ length: resumen.total_rondas }, (_, i) => i + 1)
  const rondasPorNumero = new Map(resumen.rondas.map((r) => [r.liga_ronda, r]))

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-7">
        {numeros.map((numero) => {
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
                className="mt-1 inline-block rounded-full border border-liga-borde/40 bg-white px-2 py-0.5 font-display text-xs font-bold"
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
              {numeros.map((numero) => (
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
                  className="border-t border-liga-borde/40 transition-colors hover:bg-liga-fondo/60"
                >
                  <td className="px-3 py-2 opacity-60">{indice + 1}</td>
                  <td className="px-3 py-2 font-semibold">{miembro.nombre}</td>
                  <td className="px-3 py-2">{miembro.nivel_ayuntamiento}</td>
                  {numeros.map((numero) => (
                    <td key={numero} className="px-2 py-2 text-center">
                      <CeldaRonda ronda={porRonda.get(numero)} />
                    </td>
                  ))}
                  <td className="px-3 py-2 font-bold">{miembro.estrellas_total}</td>
                  <td className="px-3 py-2">
                    {miembro.ataques_realizados} / {miembro.rondas_alineado}
                  </td>
                  <td className={`px-3 py-2 font-semibold ${miembro.ataques_perdidos > 0 ? 'text-red-700' : ''}`}>
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
  )
}