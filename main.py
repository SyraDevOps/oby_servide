from flask import Flask, Response, request, jsonify
from flask_cors import CORS
import os
import json
import unicodedata
from datetime import datetime

app = Flask(__name__)
CORS(app)

# Os arquivos .md e .json ficam na mesma pasta deste arquivo .py
BASE_DIR = os.path.dirname(os.path.abspath(__file__))

# 15 categorias principais
CATEGORIES = [
    "Ficção",
    "Não Ficção",
    "Romance",
    "Mistério / Suspense",
    "Ficção Científica",
    "Fantasia",
    "Terror / Horror",
    "Educação / Didáticos",
    "Negócios / Finanças",
    "Desenvolvimento Pessoal",
    "Infantil",
    "Jovem Adulto",
    "Aventura",
    "História",
    "Poesia",
]


# -----------------------------
# Utils
# -----------------------------
def normalize_text(value):
    """Remove acentos, padroniza para minúsculo e limpa espaços."""
    if value is None:
        return ""
    text = str(value).strip().lower()
    text = unicodedata.normalize("NFKD", text)
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    return text


def split_query_list(value):
    """
    Transforma:
      "Romance,Fantasia" -> ["Romance", "Fantasia"]
      "Romance" -> ["Romance"]
      None -> []
    """
    if not value:
        return []
    return [item.strip() for item in value.split(",") if item.strip()]


def load_json_safe(path):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Erro lendo {path}: {e}")
        return None


def is_valid_meta(meta):
    return isinstance(meta, dict) and "id" in meta and "title" in meta


def get_book_categories(meta):
    """
    Aceita tanto:
      - "category": "Romance"
      - "categories": ["Romance", "Fantasia"]
    """
    raw = []

    if isinstance(meta, dict):
        if "categories" in meta and meta["categories"] is not None:
            if isinstance(meta["categories"], list):
                raw.extend(meta["categories"])
            else:
                raw.append(meta["categories"])

        if "category" in meta and meta["category"]:
            raw.append(meta["category"])

        if "categoria" in meta and meta["categoria"]:
            raw.append(meta["categoria"])

        if "categorias" in meta and meta["categorias"] is not None:
            if isinstance(meta["categorias"], list):
                raw.extend(meta["categorias"])
            else:
                raw.append(meta["categorias"])

    cleaned = []
    for item in raw:
        if isinstance(item, str):
            item = item.strip()
            if item:
                cleaned.append(item)

    # remove duplicados preservando ordem
    seen = set()
    result = []
    for item in cleaned:
        norm = normalize_text(item)
        if norm not in seen:
            seen.add(norm)
            result.append(item)

    return result


def book_matches_categories(meta, wanted_categories):
    """Retorna True se o livro pertencer a qualquer uma das categorias desejadas."""
    if not wanted_categories:
        return True

    book_categories = get_book_categories(meta)
    book_categories_norm = {normalize_text(cat) for cat in book_categories}
    wanted_norm = {normalize_text(cat) for cat in wanted_categories}

    return bool(book_categories_norm & wanted_norm)


def build_search_text(meta):
    """
    Campos usados na busca.
    """
    parts = [
        meta.get("title", ""),
        meta.get("author", ""),
        meta.get("description", ""),
        meta.get("summary", ""),
        meta.get("synopsis", ""),
    ]

    tags = meta.get("tags", [])
    if isinstance(tags, list):
        parts.extend(tags)
    else:
        parts.append(str(tags))

    parts.extend(get_book_categories(meta))
    return normalize_text(" ".join(map(str, parts)))


def get_sort_timestamp(meta):
    """
    Ordena por updated_at, depois created_at, depois 0.
    Espera formato ISO 8601, mas se não conseguir parsear, retorna 0.
    """
    for key in ("updated_at", "created_at", "date", "published_at"):
        value = meta.get(key)
        if value:
            try:
                iso_value = str(value).replace("Z", "+00:00")
                return datetime.fromisoformat(iso_value).timestamp()
            except Exception:
                pass
    return 0


def load_all_books():
    books = []

    for file in os.listdir(BASE_DIR):
        if not file.endswith(".json"):
            continue

        if file.startswith("__"):
            continue

        path = os.path.join(BASE_DIR, file)
        meta = load_json_safe(path)

        if not meta or not is_valid_meta(meta):
            continue

        books.append(meta)

    books.sort(key=get_sort_timestamp, reverse=True)
    return books


def filter_books_by_categories(books, categories):
    if not categories:
        return books
    return [book for book in books if book_matches_categories(book, categories)]


def search_books_in_list(books, query):
    if not query:
        return books

    q = normalize_text(query)
    results = []

    for meta in books:
        text = build_search_text(meta)
        if q in text:
            results.append(meta)

    return results


# -----------------------------
# Routes
# -----------------------------
@app.route("/", methods=["GET"])
def health():
    return jsonify({
        "status": "ok",
        "service": "books-api",
        "base_dir": BASE_DIR
    })


@app.route("/categories", methods=["GET"])
def list_categories():
    """
    Lista as 15 categorias principais.
    Também devolve quantos livros existem em cada uma.
    """
    books = load_all_books()
    output = []

    for category in CATEGORIES:
        count = sum(
            1 for book in books
            if book_matches_categories(book, [category])
        )
        output.append({
            "name": category,
            "slug": normalize_text(category).replace(" ", "-"),
            "total": count
        })

    return jsonify({
        "categories": output,
        "total": len(output)
    })


@app.route("/books", methods=["GET"])
def list_books():
    """
    Lista todos os livros.
    Filtros opcionais:
      /books?category=Romance
      /books?categories=Romance,Fantasia
    """
    books = load_all_books()

    category = request.args.get("category", "").strip()
    categories = split_query_list(request.args.get("categories", "").strip())

    if category:
        categories = [category]

    books = filter_books_by_categories(books, categories)

    return jsonify({
        "books": books,
        "total": len(books)
    })


@app.route("/books/category/<path:category>", methods=["GET"])
def list_books_by_category(category):
    """
    Lista livros de uma categoria específica.
    Ex:
      /books/category/Romance
      /books/category/Mistério%20/%20Suspense
    """
    books = load_all_books()
    books = filter_books_by_categories(books, [category])

    return jsonify({
        "category": category,
        "books": books,
        "total": len(books)
    })


@app.route("/books/categories/<path:categories>", methods=["GET"])
def list_books_by_multiple_categories(categories):
    """
    Lista livros de uma ou mais categorias.
    Ex:
      /books/categories/Romance,Fantasia
    """
    wanted = split_query_list(categories)
    books = load_all_books()
    books = filter_books_by_categories(books, wanted)

    return jsonify({
        "categories": wanted,
        "books": books,
        "total": len(books)
    })


@app.route("/books/<book_id>", methods=["GET"])
def get_book(book_id):
    file_path = os.path.join(BASE_DIR, f"{book_id}.md")

    if not os.path.exists(file_path):
        return jsonify({"error": "Livro não encontrado"}), 404

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Erro lendo {file_path}: {e}")
        return jsonify({"error": "Erro ao ler arquivo"}), 500

    return Response(content, mimetype="text/markdown")


@app.route("/books/<book_id>/meta", methods=["GET"])
def get_meta(book_id):
    meta_path = os.path.join(BASE_DIR, f"{book_id}.json")

    if not os.path.exists(meta_path):
        return jsonify({"error": "Metadata não encontrada"}), 404

    meta = load_json_safe(meta_path)

    if not meta:
        return jsonify({"error": "Erro ao ler metadata"}), 500

    return jsonify(meta)


@app.route("/books/<book_id>/download", methods=["GET"])
def download_book(book_id):
    file_path = os.path.join(BASE_DIR, f"{book_id}.md")

    if not os.path.exists(file_path):
        return jsonify({"error": "Livro não encontrado"}), 404

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Erro lendo {file_path}: {e}")
        return jsonify({"error": "Erro ao ler arquivo"}), 500

    return Response(
        content,
        mimetype="text/markdown",
        headers={
            "Content-Disposition": f'attachment; filename="{book_id}.md"'
        }
    )


@app.route("/search", methods=["GET"])
def search_books():
    """
    Busca por título, autor, tags, descrição e categoria.
    Filtros opcionais:
      /search?q=amor
      /search?q=amor&category=Romance
      /search?q=amor&categories=Romance,Fantasia
    """
    query = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    categories = split_query_list(request.args.get("categories", "").strip())

    if category:
        categories = [category]

    books = load_all_books()
    books = filter_books_by_categories(books, categories)
    results = search_books_in_list(books, query)

    return jsonify({
        "query": query,
        "categories": categories,
        "books": results,
        "total": len(results)
    })


@app.route("/search/category/<path:category>", methods=["GET"])
def search_books_in_category(category):
    """
    Busca dentro de uma categoria específica.
    Ex:
      /search/category/Romance?q=amor
    """
    query = request.args.get("q", "").strip()

    books = load_all_books()
    books = filter_books_by_categories(books, [category])
    results = search_books_in_list(books, query)

    return jsonify({
        "query": query,
        "category": category,
        "books": results,
        "total": len(results)
    })


@app.route("/search/categories/<path:categories>", methods=["GET"])
def search_books_in_multiple_categories(categories):
    """
    Busca dentro de várias categorias.
    Ex:
      /search/categories/Romance,Fantasia?q=amor
    """
    query = request.args.get("q", "").strip()
    wanted = split_query_list(categories)

    books = load_all_books()
    books = filter_books_by_categories(books, wanted)
    results = search_books_in_list(books, query)

    return jsonify({
        "query": query,
        "categories": wanted,
        "books": results,
        "total": len(results)
    })


# -----------------------------
# Cloud Functions / WSGI entrypoint
# -----------------------------
def main(request):
    """
    Entry point para Cloud Functions.
    """
    with app.request_context(request.environ):
        return app.full_dispatch_request()
