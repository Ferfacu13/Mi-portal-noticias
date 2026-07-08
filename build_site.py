name: Actualizar sitio de noticias

on:
  schedule:
    - cron: "0 */1 * * *"   # corre cada 1 hora, automáticamente, para siempre
  workflow_dispatch: {}       # también podés dispararlo a mano desde GitHub si querés

permissions:
  contents: write

jobs:
  build-and-deploy:
    runs-on: ubuntu-latest
    steps:
      - name: Descargar el repositorio
        uses: actions/checkout@v4

      - name: Configurar Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.11"

      - name: Generar el sitio (leer feeds y armar HTML)
        run: python scripts/build_site.py

      - name: Publicar en GitHub Pages
        uses: peaceiris/actions-gh-pages@v4
        with:
          github_token: ${{ secrets.GITHUB_TOKEN }}
          publish_dir: ./site
