import type { ClanClasificacion } from '../../api/liga'

/** Clasificación del grupo: los ocho clanes ordenados por estrellas y, a igualdad, por destrucción. */
export function TablaClasificacion({ clasificacion }: { clasificacion: ClanClasificacion[] }) {
  return (
    <div className="overflow-x-auto rounded-xl border-2 border-liga-borde bg-liga-panel">
      <table className="w-full text-left">
        <thead className="font-display">
          <tr className="border-b-2 border-liga-borde">
            <th className="px-3 py-2">Pos.</th>
            <th className="px-3 py-2">Clan</th>
            <th className="px-3 py-2">⭐ Estrellas</th>
            <th className="px-3 py-2">Destrucción</th>
            <th className="px-3 py-2 text-center">V</th>
            <th className="px-3 py-2 text-center">D</th>
            <th className="px-3 py-2 text-center">E</th>
          </tr>
        </thead>
        <tbody>
          {clasificacion.map((clan) => (
            <tr
              key={clan.tag}
              className={`border-t border-liga-borde/40 transition-colors ${
                clan.es_propio ? 'bg-liga-acento/30 font-bold' : 'hover:bg-liga-fondo/60'
              }`}
            >
              <td className="px-3 py-2">{clan.posicion}</td>
              <td className="px-3 py-2">
                {clan.nombre} <span className="text-sm font-normal opacity-60">(nivel {clan.nivel})</span>
              </td>
              <td
                className="px-3 py-2"
                title={`${clan.estrellas_en_combate} en combate + ${clan.estrellas_bono} de bono por victorias`}
              >
                {clan.estrellas}
              </td>
              <td className="px-3 py-2">{clan.destruccion.toLocaleString('es-PE')}</td>
              <td className="px-3 py-2 text-center">{clan.victorias}</td>
              <td className="px-3 py-2 text-center">{clan.derrotas}</td>
              <td className="px-3 py-2 text-center">{clan.empates}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}