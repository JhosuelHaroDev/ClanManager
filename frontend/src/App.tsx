import { Route, Routes } from 'react-router-dom'
import { DisenoPrincipal } from './componentes/DisenoPrincipal'
import { PaginaGuerra } from './paginas/PaginaGuerra'
import { PaginaMiembros } from './paginas/PaginaMiembros'
import { PaginaLiga } from './paginas/PaginaLiga'

function App() {
  return (
    <Routes>
      <Route element={<DisenoPrincipal />}>
        <Route path="/" element={<PaginaMiembros />} />
        <Route path="/guerra" element={<PaginaGuerra />} />
        <Route path="/liga" element={<PaginaLiga />} />
        {/* La ruta de asaltos se agrega junto con su pantalla. */}
        {/* Las rutas de liga y asaltos se agregan junto con cada pantalla. */}
      </Route>
    </Routes>
  )
}

export default App