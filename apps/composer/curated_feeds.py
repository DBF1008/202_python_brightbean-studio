"""Curated RSS feed catalog for the Explore Feeds modal.

Categories and feeds are stored as static data - they don't change
per-workspace and don't need database storage.
"""

from urllib.parse import urlsplit

FEED_CATEGORIES = [
    {"slug": "brightbean-favorites", "label": "Brightbean Favorites"},
    {"slug": "tech", "label": "Tech"},
    {"slug": "news", "label": "News"},
    {"slug": "business", "label": "Business"},
    {"slug": "art-media", "label": "Art & Media"},
    {"slug": "entertainment", "label": "Entertainment"},
    {"slug": "science", "label": "Science"},
]

CURATED_FEEDS = {
    "brightbean-favorites": [
        {"name": "Creator Science", "website": "https://creatorscience.com/", "rss": "https://creatorscience.com/rss/"},
        {
            "name": "Lindsey Gamble's Newsletter",
            "website": "https://lindseygamble.com/",
            "rss": "https://rss.beehiiv.com/feeds/3W8tiKSkqq",
        },
        {"name": "Passionfruit", "website": "https://passionfru.it/", "rss": "https://passionfru.it/feed/"},
        {
            "name": "ICYMI by Lia Haberman",
            "website": "https://liahaberman.substack.com/",
            "rss": "https://liahaberman.substack.com/feed",
        },
        {"name": "Link in Bio", "website": "https://www.milkkarten.net/", "rss": "https://www.milkkarten.net/feed"},
        {
            "name": "Geekout Newsletter",
            "website": "https://geekout.beehiiv.com/",
            "rss": "https://rss.beehiiv.com/feeds/e2fyt",
        },
        {"name": "SparkToro Blog", "website": "https://sparktoro.com/blog/", "rss": "https://sparktoro.com/blog/feed/"},
        {"name": "Buffer Blog", "website": "https://buffer.com/resources/", "rss": "https://buffer.com/resources/rss/"},
    ],
    "tech": [
        {"name": "Engadget", "website": "https://www.engadget.com/", "rss": "https://www.engadget.com/rss.xml"},
        {"name": "The Verge", "website": "https://www.theverge.com/", "rss": "https://www.theverge.com/rss/index.xml"},
        {"name": "Wired", "website": "https://www.wired.com/", "rss": "https://www.wired.com/feed/rss"},
        {"name": "TechCrunch", "website": "https://techcrunch.com/", "rss": "https://techcrunch.com/feed/"},
        {"name": "Lifehacker", "website": "https://lifehacker.com/", "rss": "https://lifehacker.com/feed/rss"},
        {"name": "Gizmodo", "website": "https://gizmodo.com/", "rss": "https://gizmodo.com/feed"},
        {"name": "Mashable", "website": "https://mashable.com/", "rss": "https://mashable.com/feeds/rss/all"},
        {
            "name": "Fast Company",
            "website": "https://www.fastcompany.com/",
            "rss": "https://feeds.feedburner.com/fastcompany/headlines",
        },
        {
            "name": "Ars Technica",
            "website": "https://arstechnica.com/",
            "rss": "https://feeds.arstechnica.com/arstechnica/features",
        },
        {"name": "The Keyword - Google", "website": "https://blog.google/", "rss": "https://blog.google/rss/"},
        {
            "name": "MacRumors",
            "website": "https://www.macrumors.com/",
            "rss": "https://feeds.macrumors.com/MacRumors-All",
        },
        {
            "name": "Android Central",
            "website": "https://www.androidcentral.com/",
            "rss": "https://www.androidcentral.com/feed",
        },
        {
            "name": "TED Talks",
            "website": "https://www.ted.com/talks",
            "rss": "https://feeds.feedburner.com/tedtalks_video",
        },
        {
            "name": "Slashdot",
            "website": "https://slashdot.org/",
            "rss": "https://rss.slashdot.org/Slashdot/slashdotMain",
        },
        {
            "name": "VentureBeat",
            "website": "https://venturebeat.com/",
            "rss": "https://feeds.feedburner.com/venturebeat/SZYF",
        },
        {"name": "TheNextWeb", "website": "https://thenextweb.com/", "rss": "https://feeds2.feedburner.com/thenextweb"},
        {"name": "Hackaday", "website": "https://hackaday.com/", "rss": "https://hackaday.com/blog/feed"},
        {"name": "Make Magazine", "website": "https://makezine.com/", "rss": "https://makezine.com/feed/"},
        {
            "name": "MIT Technology Review",
            "website": "https://technologyreview.com/",
            "rss": "https://www.technologyreview.com/feed/",
        },
        {"name": "Hacker News", "website": "https://news.ycombinator.com/", "rss": "https://news.ycombinator.com/rss"},
        {"name": "9to5Mac", "website": "https://9to5mac.com/", "rss": "https://9to5mac.com/feed/"},
        {"name": "Cnet", "website": "https://www.cnet.com/", "rss": "https://www.cnet.com/rss/news/"},
        {
            "name": "Technology - The New York Times",
            "website": "https://www.nytimes.com/section/technology",
            "rss": "https://www.nytimes.com/svc/collections/v1/publish/https:/www.nytimes.com/section/technology/rss.xml",
        },
    ],
    "news": [
        {"name": "BBC News", "website": "https://www.bbc.co.uk/news", "rss": "https://feeds.bbci.co.uk/news/rss.xml"},
        {
            "name": "The New York Times",
            "website": "https://nytimes.com/",
            "rss": "https://rss.nytimes.com/services/xml/rss/nyt/HomePage.xml",
        },
        {
            "name": "The Guardian",
            "website": "https://www.theguardian.com/",
            "rss": "https://www.theguardian.com/uk/rss",
        },
        {"name": "NPR", "website": "https://www.npr.org/", "rss": "https://feeds.npr.org/1001/rss.xml"},
        {
            "name": "The World This Week | The Economist",
            "website": "https://www.economist.com/the-world-this-week/",
            "rss": "https://www.economist.com/the-world-this-week/rss.xml",
        },
        {"name": "Time", "website": "https://time.com/", "rss": "https://time.com/feed/"},
        {"name": "Slate Magazine", "website": "https://slate.com/", "rss": "https://slate.com/feeds/all.rss"},
        {
            "name": "The Atlantic",
            "website": "https://www.theatlantic.com/",
            "rss": "https://www.theatlantic.com/feed/all/",
        },
        {"name": "Yahoo News", "website": "https://www.yahoo.com/news", "rss": "https://news.yahoo.com/rss"},
        {"name": "ABC News", "website": "https://abcnews.go.com/", "rss": "https://abcnews.go.com/abcnews/topstories"},
        {
            "name": "Culture - The New Yorker",
            "website": "https://www.newyorker.com/culture",
            "rss": "https://www.newyorker.com/feed/culture",
        },
        {"name": "Vice", "website": "https://www.vice.com/en/", "rss": "https://www.vice.com/en/feed/"},
        {"name": "Politico", "website": "https://politico.com/", "rss": "https://rss.politico.com/politics-news.xml"},
        {"name": "Vox", "website": "https://vox.com/", "rss": "https://www.vox.com/rss/index.xml"},
        {
            "name": "The Washington Post",
            "website": "https://www.washingtonpost.com/world/",
            "rss": "https://feeds.washingtonpost.com/rss/world",
        },
        {"name": "Al Jazeera", "website": "https://aljazeera.com/", "rss": "https://www.aljazeera.com/xml/rss/all.xml"},
    ],
    "business": [
        {
            "name": "Business Insider",
            "website": "https://www.businessinsider.com/",
            "rss": "https://feeds2.feedburner.com/businessinsider",
        },
        {
            "name": "Fast Company",
            "website": "https://www.fastcompany.com/",
            "rss": "https://feeds.feedburner.com/fastcompany/headlines",
        },
        {
            "name": "Harvard Business Review",
            "website": "https://hbr.org/",
            "rss": "https://hbr.org/resources/xml/atom/tip.xml",
        },
        {"name": "Seth's Blog", "website": "https://seths.blog/", "rss": "https://seths.blog/feed/atom/"},
        {
            "name": "Entrepreneur",
            "website": "https://www.entrepreneur.com/",
            "rss": "https://www.entrepreneur.com/rss-feed/latest",
        },
        {
            "name": "The World This Week | The Economist",
            "website": "https://www.economist.com/the-world-this-week/",
            "rss": "https://www.economist.com/the-world-this-week/rss.xml",
        },
        {
            "name": "The Hubspot Marketing Blog",
            "website": "https://blog.hubspot.com/marketing",
            "rss": "https://blog.hubspot.com/marketing/rss.xml",
        },
        {"name": "Time", "website": "https://time.com/", "rss": "https://time.com/feed/"},
        {
            "name": "VentureBeat",
            "website": "https://venturebeat.com/",
            "rss": "https://feeds.feedburner.com/venturebeat/SZYF",
        },
        {"name": "Copyblogger", "website": "https://copyblogger.com/", "rss": "https://copyblogger.com/feed/"},
        {"name": "Inc. Magazine", "website": "https://www.inc.com/", "rss": "https://www.inc.com/rss"},
        {
            "name": "Business - The New York Times",
            "website": "https://www.nytimes.com/section/business",
            "rss": "https://www.nytimes.com/svc/collections/v1/publish/https:/www.nytimes.com/section/business/rss.xml",
        },
        {"name": "Tim Ferris", "website": "https://tim.blog/", "rss": "https://tim.blog/feed/"},
        {
            "name": "Small Business Trends",
            "website": "https://smallbiztrends.com/",
            "rss": "https://feeds.feedburner.com/SmallBusinessTrends",
        },
    ],
    "art-media": [
        {"name": "Design Milk", "website": "https://design-milk.com/", "rss": "https://design-milk.com/feed/"},
        {"name": "Colossal", "website": "https://thisiscolossal.com/", "rss": "https://www.thisiscolossal.com/feed/"},
        {
            "name": "It's Nice That",
            "website": "https://itsnicethat.com/",
            "rss": "https://feeds2.feedburner.com/itsnicethat/SlXC",
        },
        {"name": "Booooooom", "website": "https://www.booooooom.com/", "rss": "https://www.booooooom.com/feed/"},
        {
            "name": "Contemporary Art Daily",
            "website": "https://contemporaryartdaily.com/",
            "rss": "https://www.contemporaryartdaily.com/feed/",
        },
        {"name": "Post Secret", "website": "https://postsecret.com/", "rss": "https://postsecret.com/feed/"},
        {"name": "Ignant", "website": "https://www.ignant.com/", "rss": "https://www.ignant.com/feed/"},
        {
            "name": "this isn't happiness",
            "website": "https://thisisnthappiness.com/",
            "rss": "https://feeds.feedburner.com/thisisnthappiness",
        },
        {"name": "Hyperallergic", "website": "https://hyperallergic.com/", "rss": "https://hyperallergic.com/feed/"},
        {"name": "ArtsJournal", "website": "https://www.artsjournal.com/", "rss": "https://www.artsjournal.com/feed"},
        {
            "name": "Art and Design - The New York Times",
            "website": "https://www.nytimes.com/section/arts/design",
            "rss": "https://www.nytimes.com/svc/collections/v1/publish/https:/www.nytimes.com/section/arts/design/rss.xml",
        },
        {"name": "ARTNews", "website": "https://www.artnews.com/", "rss": "https://www.artnews.com/feed/rss/"},
        {"name": "Hi-Fructose Magazine", "website": "https://hifructose.com/", "rss": "https://hifructose.com/feed/"},
        {"name": "Artsy", "website": "https://www.artsy.net/", "rss": "https://www.artsy.net/rss/news"},
    ],
    "entertainment": [
        {"name": "Buzzfeed", "website": "https://www.buzzfeed.com/", "rss": "https://www.buzzfeed.com/index.xml"},
        {
            "name": "Rolling Stone",
            "website": "https://www.rollingstone.com/",
            "rss": "https://www.rollingstone.com/feed/rss/",
        },
        {"name": "SlashFilm", "website": "https://www.slashfilm.com/", "rss": "https://feeds.feedburner.com/slashfilm"},
        {"name": "IndieWire", "website": "https://www.indiewire.com/", "rss": "https://www.indiewire.com/feed/rss/"},
        {"name": "TMZ.com", "website": "https://tmz.com/", "rss": "https://www.tmz.com/rss.xml"},
        {
            "name": "Cracked.com",
            "website": "https://www.cracked.com/",
            "rss": "https://feeds.feedburner.com/CrackedRSS",
        },
        {"name": "Deadline.com", "website": "https://deadline.com/", "rss": "https://deadline.com/feed/rss/"},
        {
            "name": "Movies - The New York Times",
            "website": "https://www.nytimes.com/section/movies",
            "rss": "https://www.nytimes.com/svc/collections/v1/publish/https:/www.nytimes.com/section/movies/rss.xml",
        },
        {"name": "Vulture", "website": "https://www.vulture.com/", "rss": "https://feeds.feedburner.com/nymag/vulture"},
        {"name": "Variety", "website": "https://variety.com/", "rss": "https://variety.com/feed/rss/"},
        {
            "name": "Ain't It Cool News",
            "website": "https://www.aintitcool.com/",
            "rss": "https://www.aintitcool.com/node/feed/",
        },
        {"name": "Nerdist", "website": "https://nerdist.com/", "rss": "https://nerdist.com/feed/"},
    ],
    "science": [
        {"name": "Wired", "website": "https://www.wired.com/", "rss": "https://www.wired.com/feed/rss"},
        {
            "name": "Scientific American",
            "website": "https://www.scientificamerican.com/",
            "rss": "https://www.scientificamerican.com/platform/syndication/rss/",
        },
        {
            "name": "Science Journal",
            "website": "https://science.org/",
            "rss": "https://www.science.org/rss/news_current.xml",
        },
        {
            "name": "MIT Technology Review",
            "website": "https://technologyreview.com/",
            "rss": "https://www.technologyreview.com/feed/",
        },
        {"name": "Nature", "website": "https://nature.com/", "rss": "https://www.nature.com/nature.rss"},
        {
            "name": "New Scientist",
            "website": "https://newscientist.com/",
            "rss": "https://www.newscientist.com/feed/home/",
        },
        {
            "name": "ScienceDaily",
            "website": "https://sciencedaily.com/",
            "rss": "https://www.sciencedaily.com/rss/all.xml",
        },
        {"name": "Space.com", "website": "https://space.com/", "rss": "https://www.space.com/feeds.xml"},
        {
            "name": "Science - The New York Times",
            "website": "https://nytimes.com/",
            "rss": "https://www.nytimes.com/svc/collections/v1/publish/https:/www.nytimes.com/section/science/rss.xml",
        },
        {
            "name": "Information is Beautiful",
            "website": "https://informationisbeautiful.net/",
            "rss": "https://feeds.feedburner.com/InformationIsBeautiful",
        },
        {"name": "Futurity", "website": "https://futurity.org/", "rss": "https://www.futurity.org/feed/"},
        {"name": "Phys.org", "website": "https://phys.org/", "rss": "https://phys.org/rss-feed/"},
        {"name": "Futurism", "website": "https://futurism.com/", "rss": "https://futurism.com/feed"},
        {
            "name": "Science and Technology | The Economist",
            "website": "https://economist.com/",
            "rss": "https://www.economist.com/science-and-technology/rss.xml",
        },
    ],
}


def get_feed_categories():
    return FEED_CATEGORIES


def _build_favicon_url(website_url):
    """Return a best-effort favicon URL for a feed website."""
    if not website_url:
        return ""

    parsed = urlsplit(website_url)
    if not parsed.scheme or not parsed.netloc:
        return ""

    return f"{parsed.scheme}://{parsed.netloc}/favicon.ico"


def get_feeds_for_category(slug):
    feeds = CURATED_FEEDS.get(slug, [])
    return [
        {
            **feed,
            "favicon": _build_favicon_url(feed.get("website", "")),
        }
        for feed in feeds
    ]
