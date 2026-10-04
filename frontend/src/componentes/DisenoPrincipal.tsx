import { NavLink, Outlet } from 'react-router-dom'

const enlaces = [
  { ruta: '/', etiqueta: 'Miembros' },
  { ruta: '/guerra', etiqueta: 'Guerra' },
  // Los enlaces de liga y asaltos se agregan junto con cada pantalla.
]

/**
 * Armazón visual compartido por toda la aplicación: encabezado con el
 * nombre y la navegación, y un área central donde React Router dibuja
 * la pantalla activa a través de <Outlet />.
 */
export function DisenoPrincipal() {
  return (
    <div className="min-h-screen bg-base-fondo text-base-texto">
      <header className="border-b-4 border-base-borde bg-base-panel px-6 py-4">
        <h1 className="font-display text-2xl font-extrabold">ClanManager</h1>
        <nav className="mt-2 flex gap-4 font-display font-semibold">
          {enlaces.map((enlace) => (
            <NavLink
              key={enlace.ruta}
              to={enlace.ruta}
              end
              className={({ isActive }) =>
                isActive ? 'text-base-acento underline' : 'text-base-texto/70 hover:text-base-texto'
              }
            >
              {enlace.etiqueta}
            </NavLink>
          ))}
        </nav>
      </header>
      <main className="p-6">
        <Outlet />
      </main>
    </div>
  )
}