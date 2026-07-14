import { createApp } from 'vue'
import { createPinia } from 'pinia'
import App from './App.vue'
import router from './router'
import naive from 'naive-ui'
import { i18n } from './i18n'
import 'vue-click-to-component/client'

if (import.meta.env.DEV) {
  window.__VUE_CLICK_TO_COMPONENT_URL_FUNCTION__ = function ({ sourceCodeLocation }) {
    const wslTarget = 'Ubuntu-24.04'
    return `vscode://vscode-remote/wsl+${wslTarget}/${sourceCodeLocation}`
  }
}

import './styles/variables.css'
import './styles/global.css'
import './styles/naive-overrides.css'

window.addEventListener('unhandledrejection', (event) => {
	const reason = event.reason
	if (reason instanceof DOMException && reason.name === 'AbortError') {
		const message = reason.message || ''
		if (message.includes('play()') || message.includes('play request')) {
			event.preventDefault()
		}
	}
})

const app = createApp(App)
app.use(createPinia())
app.use(router)
app.use(naive)
app.use(i18n)
app.mount('#app')
