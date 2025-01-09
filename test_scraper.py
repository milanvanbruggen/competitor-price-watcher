from scraper import MaterialScraper
import time

def test_scraper():
    scraper = MaterialScraper()
    
    test_cases = [
        {
            "url": "https://website1.nl",
            "dimensions": {
                "length": 100,
                "width": 50,
                "thickness": 2
            },
            "description": "Basis test website1"
        },
        {
            "url": "https://website2.nl",
            "dimensions": {
                "length": 200,
                "width": 75,
                "thickness": 3
            },
            "description": "Multi-step form website2"
        }
    ]
    
    for test in test_cases:
        print("\nTest: {}".format(test['description']))
        print("-" * 50)
        
        try:
            price = scraper.scrape_price(
                test['url'],
                length=test['dimensions']['length'],
                width=test['dimensions']['width'],
                thickness=test['dimensions']['thickness']
            )
            
            print("URL: {}".format(test['url']))
            print("Dimensies: {}".format(test['dimensions']))
            print("Resultaat prijs: {}".format(price))
            
        except Exception as e:
            print("Error tijdens test: {}".format(str(e)))
        
        # Wacht even tussen tests
        time.sleep(2)

if __name__ == "__main__":
    test_scraper() 