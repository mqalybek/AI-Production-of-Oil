import { useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../auth/AuthContext'
import { ApiError } from '../api/client'
import './Login.css'

export function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setIsSubmitting(true)
    try {
      await login(username, password)
      navigate('/', { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Не удалось войти')
    } finally {
      setIsSubmitting(false)
    }
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={onSubmit}>
        <h1 className="login__title">Мониторинг добычи</h1>
        <label className="login__field">
          <span>Логин</span>
          <input value={username} onChange={(e) => setUsername(e.target.value)} autoFocus required />
        </label>
        <label className="login__field">
          <span>Пароль</span>
          <input type="password" value={password} onChange={(e) => setPassword(e.target.value)} required />
        </label>
        {error && <div className="login__error">{error}</div>}
        <button className="login__submit" type="submit" disabled={isSubmitting}>
          {isSubmitting ? 'Входим…' : 'Войти'}
        </button>
      </form>
    </div>
  )
}
