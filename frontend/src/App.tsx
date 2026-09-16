import { Navigate, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { DataQuality } from './pages/DataQuality'
import { Login } from './pages/Login'
import { LossAnalysis } from './pages/LossAnalysis'
import { MorningSummary } from './pages/MorningSummary'
import { WellCardPage } from './pages/WellCardPage'
import { WellFund } from './pages/WellFund'
import { ProtectedRoute } from './ProtectedRoute'

function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        element={
          <ProtectedRoute>
            <Layout />
          </ProtectedRoute>
        }
      >
        <Route path="/" element={<MorningSummary />} />
        <Route path="/wells" element={<WellFund />} />
        <Route path="/wells/:uwi" element={<WellCardPage />} />
        <Route path="/losses" element={<LossAnalysis />} />
        <Route path="/data-quality" element={<DataQuality />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}

export default App
