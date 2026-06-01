# WEB DIR MAP v1.0 — Desktop (Electron + Python)

Versão **desktop offline** do WEB DIR MAP — mapeador recursivo de
diretórios web (Apache/Nginx "Index of"). Mesmo visual e fluxo do
[DIR MAP v0.2 original](https://github.com/), porém:

- ✅ Em vez de mapear pastas locais, **varre URLs web**
- ✅ Preserva query string customizada (ex.: `?SA`)
- ✅ Detecta arquivos sensíveis (`.env`, `wp-config`, `.git`, `.sql`, etc.)
- ✅ **Fila** de URLs (rodar várias em sequência)
- ✅ **Histórico** persistente (localStorage)
- ✅ Exporta `.MD` / `.JSON` / `.TXT` / `COPIAR`

---

## 🚀 Para o USUÁRIO FINAL

1. Baixe `WEB-DIR-MAP-1.0.0-x64.exe` (installer) **ou**
   `WEB-DIR-MAP-1.0.0-x64.portable.exe` (não instala, executa direto).
2. Execute. Pronto — **não precisa de Python instalado**.

---

## 🛠️ Para QUEM VAI BUILDAR (Windows)

### Pré-requisitos (apenas na sua máquina dev):
- **Node.js ≥ 16** — https://nodejs.org
- **Python ≥ 3.8** — https://python.org

### Build em 1 clique:
```bat
build.bat
```

### Saída:
- `dist\WEB-DIR-MAP-1.0.0-x64.exe`            ← installer NSIS
- `dist\WEB-DIR-MAP-1.0.0-x64.portable.exe`   ← portátil (sem instalar)
- `dist\win-unpacked\WEB DIR MAP.exe`         ← versão unpacked

### Build manual (passo a passo):
```bat
npm install
pip install pyinstaller requests beautifulsoup4 lxml
npm run build-python      :: gera bin\web_dir_mapper.exe (~10 MB)
npm run build-win         :: gera dist\WEB-DIR-MAP-1.0.0-x64.exe
```

---

## 🧪 Modo desenvolvedor (sem PyInstaller)

```bash
npm install
pip install requests beautifulsoup4 lxml
npm start
```
Se não houver `bin\web_dir_mapper.exe`, o Electron chama `python` /
`python3` do sistema como fallback.

---

## 📂 Estrutura

```
desktop/
├── main.js                  # Processo principal Electron (IPC, spawn)
├── index.html               # UI dark/âmbar single-page
├── web_dir_mapper.py        # Scanner Python + formatadores (UML/JSON/diagrama)
├── package.json             # Config electron-builder (NSIS + portable)
├── build.bat                # Build completo Windows
└── README.md                # Este arquivo
```

---

## 🌐 Como funciona

1. Você cola uma URL (ex.: `https://gbm.org.br/wp-includes/rest-api/`)
   e, opcionalmente, uma query string (ex.: `SA`).
2. O Electron envia os parâmetros via stdin para o `web_dir_mapper.exe`
   (binário PyInstaller) ou, em modo dev, para `python`.
3. O scanner faz BFS HTTP, parseia links com BeautifulSoup, identifica
   diretórios (URLs terminando em `/`) e arquivos, respeitando filtros
   e limites.
4. Saída JSON com a árvore + formato escolhido + estatísticas.

---

## 🔒 Segurança

- Limite duro de **100.000 itens** (configurável)
- Profundidade máxima absoluta: **50 níveis**
- Botão **CANCELAR** envia `SIGTERM`/`SIGKILL` ao processo
- Restringe varredura ao mesmo host e ao subpath do root
- Detecção heurística de arquivos sensíveis para auditoria

---

## 📜 Licença

MIT — adaptado a partir do DIR MAP v0.2 (visual e arquitetura).
