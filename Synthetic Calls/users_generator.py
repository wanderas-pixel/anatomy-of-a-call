import json
import random

def generate_users():
    print("Generating user pool...")
    
    # 35 Consumer Names
    first_names = [
        "James", "Mary", "John", "Patricia", "Robert", "Jennifer", "Michael", "Linda", 
        "William", "Elizabeth", "David", "Barbara", "Richard", "Susan", "Joseph", "Jessica", 
        "Thomas", "Sarah", "Charles", "Karen", "Christopher", "Nancy", "Daniel", "Lisa", 
        "Matthew", "Betty", "Anthony", "Margaret", "Mark", "Sandra", "Donald", "Ashley", 
        "Steven", "Kimberly", "Andrew"
    ]
    last_names = [
        "Smith", "Johnson", "Williams", "Brown", "Jones", "Garcia", "Miller", "Davis", 
        "Rodriguez", "Martinez", "Hernandez", "Lopez", "Gonzalez", "Wilson", "Anderson", 
        "Thomas", "Taylor", "Moore", "Jackson", "Martin", "Lee", "Perez", "Thompson", 
        "White", "Harris", "Sanchez", "Clark", "Ramirez", "Lewis", "Robinson", "Walker", 
        "Young", "Allen", "King", "Wright"
    ]
    
    # 15 Corporate Names (Company name, primary contact person)
    companies = [
        {"company": "TechCorp Solutions", "contact": "John Doe"},
        {"company": "Apex Financials", "contact": "Emily Vance"},
        {"company": "Global Logistics LLC", "contact": "Robert Chen"},
        {"company": "Vanguard Creative", "contact": "Sarah Jenkins"},
        {"company": "Summit Health Partners", "contact": "David Miller"},
        {"company": "Beacon Consulting", "contact": "Maria Rodriguez"},
        {"company": "Nova Retail Group", "contact": "Mark Taylor"},
        {"company": "Blue Sky Aviation", "contact": "Karen White"},
        {"company": "Pinnacle Real Estate", "contact": "Thomas Anderson"},
        {"company": "Ironwood Manufacturing", "contact": "Lisa Garcia"},
        {"company": "EcoSphere Energy", "contact": "Andrew Wilson"},
        {"company": "Quantum Innovations", "contact": "Nancy Moore"},
        {"company": "Delta Legal Services", "contact": "Michael Brown"},
        {"company": "Velocity Transportation", "contact": "Sandra Smith"},
        {"company": "OmniMedia Group", "contact": "Jessica Lopez"}
    ]
    
    consumer_plans = [
        "Unlimited 5G Mobile Plan ($65/mo)",
        "Standard 5G Mobile Plan - 20GB ($45/mo)",
        "Fiber 300 Broadband Internet ($55/mo)",
        "Fiber Gigabit Broadband Internet ($85/mo)",
        "Double Play Bundle: Fiber 500 + Digital TV ($95/mo)",
        "Triple Play Bundle: Fiber 500 + Digital TV + Voice ($110/mo)",
        "Basic Prepaid Mobile Plan ($25/mo)"
    ]
    
    corporate_plans = [
        "Business Fiber Gigabit Internet ($199/mo)",
        "Business Dedicated Fiber 500Mbps - SLA Guarantees ($349/mo)",
        "Corporate Mobility: 25x Unlimited 5G Mobile Lines ($625/mo)",
        "Corporate Mobility: 50x Unlimited 5G Mobile Lines ($1150/mo)",
        "Business Voice VoIP Suite - 10 Channels ($150/mo)",
        "Enterprise SIP Trunking - 30 Channels ($350/mo)",
        "Enterprise Dedicated Ethernet 10Gbps ($1499/mo)"
    ]
    
    user_pool = []
    
    # Generate 35 Consumers
    used_indices = set()
    for i in range(1, 36):
        # Pick unique first/last name combo
        while True:
            f_idx = random.randint(0, len(first_names)-1)
            l_idx = random.randint(0, len(last_names)-1)
            combo = (f_idx, l_idx)
            if combo not in used_indices:
                used_indices.add(combo)
                first_name = first_names[f_idx]
                last_name = last_names[l_idx]
                break
                
        customer_id = f"CUST-1{i:03d}" # CUST-1001 to CUST-1035
        phone = f"555-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        email = f"{first_name.lower()}.{last_name.lower()}@telecom-personal.com"
        pin = f"{random.randint(1000, 9999)}"
        services = random.choice(consumer_plans)
        
        user_pool.append({
            "customer_id": customer_id,
            "customer_type": "Consumer",
            "name": f"{first_name} {last_name}",
            "email": email,
            "phone": phone,
            "pin": pin,
            "services": services,
            "standing": "Good" if random.random() < 0.90 else "Past Due"
        })
        
    # Generate 15 Corporates
    for i, company_info in enumerate(companies, 1):
        customer_id = f"CUST-2{i:03d}" # CUST-2001 to CUST-2015
        phone = f"800-{random.randint(100, 999)}-{random.randint(1000, 9999)}"
        email = f"{company_info['contact'].lower().replace(' ', '.')}@{company_info['company'].lower().replace(' ', '').replace('llc', '')}.com"
        pin = f"{random.randint(100000, 999999)}" # Business clients use 6 digit security pins
        services = random.choice(corporate_plans)
        
        user_pool.append({
            "customer_id": customer_id,
            "customer_type": "Corporate",
            "name": company_info["company"],
            "contact_person": company_info["contact"],
            "email": email,
            "phone": phone,
            "pin": pin,
            "services": services,
            "standing": "Good" if random.random() < 0.85 else "Past Due"
        })
        
    with open("users.json", "w") as f:
        json.dump(user_pool, f, indent=2)
        
    print(f"Generated {len(user_pool)} users successfully and saved to users.json!")
    return user_pool

if __name__ == "__main__":
    generate_users()
