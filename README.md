# Compressor e Conversor de Vídeo e Imagem

App para **comprimir vídeos sem perda visível de qualidade** e **converter vídeos e imagens entre formatos**. Funciona direto no navegador ou instalado no seu computador; nenhum arquivo é enviado para a internet.

- **Backend (versão local):** Python + [FastAPI](https://fastapi.tiangolo.com/)
- **Vídeo:** [FFmpeg](https://ffmpeg.org/) (H.264, H.265/HEVC, AV1, VP9)
- **Imagem:** [Pillow](https://python-pillow.org/) (JPG, PNG, WebP, AVIF, GIF, BMP, TIFF)

## Duas versões

| | Versão no navegador (`web/`) | Versão local (`app/`) |
|---|---|---|
| Instalação | Nenhuma: abra **<https://lkscov3r.github.io/compressor-conversor/>** | Python + FFmpeg |
| Velocidade em vídeos | Bem mais lenta: ~45 s para 5 s de vídeo 720p (FFmpeg em WebAssembly, uma thread) | Rápida (usa todos os núcleos) |
| Tamanho máximo de vídeo | Em torno de 1 GB (limite de memória do navegador) | Sem limite prático |
| Codecs de vídeo | H.264 (e VP8 para WebM) | H.264, H.265, AV1 (e VP9 para WebM) |

Nas duas, os arquivos são processados no seu computador e nunca são enviados para um servidor.

### Versão no navegador

É uma página estática em `web/`, publicada no GitHub Pages pelo workflow `.github/workflows/pages.yml` a cada push na `main`. Vídeos são processados com o [ffmpeg.wasm](https://github.com/ffmpegwasm/ffmpeg.wasm), cujo núcleo (~32 MB) é baixado do jsDelivr na primeira vez que um vídeo é aberto. Imagens JPG, WebP e AVIF são geradas pelo próprio navegador (AVIF só aparece nos navegadores que sabem gerá-lo); PNG, GIF, BMP e TIFF passam pelo ffmpeg.wasm. Diferente da versão local, os metadados EXIF das fotos não são mantidos.

**Ativar o GitHub Pages (uma vez só):** no repositório, abra *Settings → Pages* e em *Build and deployment → Source* escolha **GitHub Actions**. O próximo push na `main` (ou *Actions → Publicar versão do navegador → Run workflow*) publica o site.

Para testar a página no seu computador: `python -m http.server 8080 -d web` e abra <http://127.0.0.1:8080> (abrir o `index.html` direto do disco não funciona, porque o navegador bloqueia o Worker do FFmpeg).

## Requisitos (versão local)

1. **Python 3.10 ou mais recente**: <https://www.python.org/downloads/>
2. **FFmpeg** (só é necessário para vídeos; imagens funcionam sem ele):
   - Windows: `winget install Gyan.FFmpeg` (depois feche e abra o terminal)
   - macOS: `brew install ffmpeg`
   - Linux (Debian/Ubuntu): `sudo apt install ffmpeg`

   Confira com `ffmpeg -version`.

## Como rodar (versão local)

```bash
git clone https://github.com/lkscov3r/compressor-conversor.git
cd compressor-conversor

# crie e ative um ambiente virtual
python -m venv .venv
# Windows:
.venv\Scripts\activate
# macOS / Linux:
source .venv/bin/activate

pip install -r requirements.txt
python -m app
```

O navegador abre em <http://127.0.0.1:8000>. Para encerrar, use `Ctrl+C` no terminal.

Opções: `python -m app --port 9000` muda a porta; `--sem-navegador` não abre o navegador automaticamente.

## Como usar

Escolha **Comprimir** ou **Converter**, ajuste as opções e arraste um ou mais arquivos para a área indicada. Cada arquivo mostra o progresso, o tamanho antes e depois e um botão **Baixar**.

### Comprimir

| Nível | Vídeo (CRF H.265 / H.264 / AV1) | Imagem (qualidade JPEG / WebP / AVIF) |
|---|---|---|
| Alta qualidade (padrão) | 20 / 18 / 24, visualmente sem perdas | 90 / 90 / 80, cor sem subamostragem no JPEG |
| Equilibrada | 24 / 22 / 30 | 82 / 82 / 65 |
| Máxima compressão | 28 / 26 / 36 | 70 / 70 / 50; PNG reduzido a 256 cores |

- Vídeos saem em **MP4**, com a mesma resolução e taxa de quadros. O áudio é copiado sem recodificar quando o MP4 aceita o codec (AAC, MP3, Opus etc.); caso contrário vira AAC 192 kbps.
- **H.265** é o padrão: gera arquivos bem menores que H.264 com a mesma qualidade. Use **H.264** se o vídeo precisar tocar em aparelhos antigos. **AV1** comprime ainda mais, mas é bem mais lento.
- Imagens mantêm o formato original (BMP vira PNG). PNG é otimizado sem perdas nos níveis alta e equilibrada.
- Se o arquivo de origem já estiver muito comprimido, o resultado pode ficar maior; o app mostra quando isso acontece.

### Converter

- **Vídeo → MP4, MKV, MOV, WebM, AVI ou GIF.** Sempre que o destino aceita os codecs originais, as faixas são apenas copiadas para o novo contêiner (rápido e sem nenhuma perda). Quando não aceita, o vídeo é recodificado (H.264 em MP4/MOV/AVI, VP9 em WebM).
- **Imagem → JPG, PNG, WebP, AVIF, GIF, BMP ou TIFF.** A orientação da foto (EXIF) é aplicada e os metadados e o perfil de cor são mantidos. Transparência vira fundo branco em JPG e BMP. Marque **Imagens sem perdas** para WebP/AVIF sem perda.

## Arquivos temporários

Os envios e resultados ficam na pasta `dados/` do projeto. O arquivo enviado é apagado assim que o processamento termina, os resultados são removidos 2 horas depois e tudo que sobrar é limpo na próxima vez que o app abrir. Para usar outra pasta, defina a variável de ambiente `COMPRESSOR_DATA_DIR`.

## Testes

```bash
pip install -r requirements-dev.txt
pytest
```

Os testes de vídeo são pulados automaticamente se o FFmpeg não estiver instalado.

## Estrutura

```
app/
  __main__.py   inicia o servidor (python -m app)
  main.py       rotas da API e arquivos estáticos
  jobs.py       fila de tarefas em segundo plano
  video.py      comandos do FFmpeg (compressão, conversão, progresso)
  image.py      compressão e conversão com Pillow
  static/       interface web (HTML, CSS, JS)
tests/          testes automatizados
```
