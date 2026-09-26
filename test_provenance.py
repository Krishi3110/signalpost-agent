from scraper import canonicalize_url

def test_provenance():
    assert canonicalize_url("https://www.example.com") == "https://www.example.com"
    assert canonicalize_url("https://www.example.com/") == "https://www.example.com"
    assert canonicalize_url("https://www.example.com:443/") == "https://www.example.com"
    assert canonicalize_url("http://www.example.com:80") == "http://www.example.com"
    assert canonicalize_url("https://www.example.com/about/") == "https://www.example.com/about"
    assert canonicalize_url("https://www.example.com/about") == "https://www.example.com/about"
    
    print("✅ All provenance canonicalization tests passed!")

if __name__ == "__main__":
    test_provenance()
