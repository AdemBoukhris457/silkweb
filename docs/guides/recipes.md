# Recipes Library

Silkweb ships with built-in recipes for popular websites — pre-configured extraction templates you can run with a single command.

## Listing recipes

```python
import silkweb

for recipe in silkweb.recipes.list():
    print(f"{recipe.name}: {recipe.description}")
```

Or via CLI:

```bash
silkweb recipes list
```

## Running a recipe

```python
result = silkweb.recipes.run("hacker-news", url="https://news.ycombinator.com")
```

```bash
silkweb recipes run hacker-news --output hn.json
```

When a recipe uses **SilkQL** (`silkql_query`), `--output` writes **`QueryResult.data`** (the list of merged root models), same as if you had called `query` and passed the rows to the file writers.

## Viewing a recipe

```python
print(silkweb.recipes.show("hacker-news"))
```

```bash
silkweb recipes show hacker-news
```

## Built-in recipes

### hacker-news

Extracts stories from Hacker News front page.

| Field | Description |
|-------|-------------|
| `title` | Story title |
| `url` | Link URL |
| `score` | Points (int) |
| `author` | Submitter username |
| `comments` | Comment count (int) |

### github-repo

Extracts repository information from GitHub.

| Field | Description |
|-------|-------------|
| `name` | Repository name |
| `description` | Repo description |
| `stars` | Star count (int) |
| `language` | Primary language |
| `forks` | Fork count (int) |

### amazon-product

Extracts product details from Amazon product pages.

| Field | Description |
|-------|-------------|
| `name` | Product name |
| `price` | Price (currency) |
| `rating` | Star rating (float) |
| `reviews_count` | Number of reviews (int) |
| `availability` | In stock status |

### google-serp

Extracts search results from Google.

| Field | Description |
|-------|-------------|
| `title` | Result title |
| `url` | Result URL |
| `snippet` | Description snippet |
| `position` | Result position (int) |

### reddit-posts

Extracts posts from Reddit subreddits.

| Field | Description |
|-------|-------------|
| `title` | Post title |
| `author` | Username |
| `score` | Upvotes (int) |
| `comments` | Comment count (int) |
| `url` | Post URL |

### news-article

Extracts content from news article pages.

| Field | Description |
|-------|-------------|
| `title` | Article title |
| `author` | Author name |
| `date` | Publication date |
| `content` | Article body text |

### product-listing

Generic recipe for e-commerce product listing pages.

| Field | Description |
|-------|-------------|
| `name` | Product name |
| `price` | Price (currency) |
| `image_url` | Product image URL |
| `product_url` | Product page link |
| `rating` | Star rating (float, optional) |

## Recipe file format

Recipes are YAML files stored in `silkweb/recipes/`. Each recipe contains:

```yaml
name: hacker-news
description: Extract stories from Hacker News
url_pattern: "https://news.ycombinator.com*"
fetch_tier: 0
silkql_query: |
  {
    stories[] {
      title
      url
      score(int)
      author
      comments(int)
    }
  }
notes: "Simple static page, Tier 0 is sufficient"
```

| Field | Description |
|-------|-------------|
| `name` | Recipe identifier |
| `description` | Human-readable description |
| `url_pattern` | URL pattern this recipe applies to |
| `fetch_tier` | Recommended fetcher tier |
| `silkql_query` | SilkQL query string (or `schema` for Pydantic) |
| `wait_for` | CSS selector to wait for (optional, for JS pages) |
| `notes` | Usage notes |
