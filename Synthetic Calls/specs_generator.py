import json
import random

def generate_specs():
    print("Generating 100 call specifications...")
    
    with open("users.json", "r") as f:
        users = json.load(f)
        
    # Categories list
    categories = [
        "Account and PIN questions",
        "Billing problems",
        "Technical issues e.g. outages and technical difficulties with equipment",
        "New orders",
        "Payments"
    ]
    
    # Refined user weights for broader coverage:
    # 5 users: 0 weight (not represented)
    # 5 users: heavy callers (weight = 5)
    # 10 users: medium callers (weight = 2)
    # 30 users: standard/light callers (weight = 1)
    
    users_shuffled = list(users)
    random.shuffle(users_shuffled)
    
    user_weights = {}
    
    # Assign weights
    for idx, user in enumerate(users_shuffled):
        uid = user["customer_id"]
        if idx < 5:
            user_weights[uid] = 0 # Not represented at all
        elif idx < 10:
            user_weights[uid] = 5 # Heavy callers
        elif idx < 20:
            user_weights[uid] = 2 # Medium callers
        else:
            user_weights[uid] = 1 # Standard callers
            
    # Normalize weights to choose
    choice_pool = []
    for user in users:
        uid = user["customer_id"]
        weight = user_weights[uid]
        choice_pool.extend([user] * weight)
        
    # Blueprints for telecom call reasons by category
    blueprints = {
        "Account and PIN questions": [
            {
                "topic": "Forgot PIN & Account Lockout",
                "summary": "Customer has forgotten their voice/security PIN and is locked out of their automated portal. Needs verification and a new PIN."
            },
            {
                "topic": "Add Authorized Contact on Corporate Account",
                "summary": "Corporate primary contact wants to add their new office/operation manager as an authorized contact to make modifications. Requires admin authorization."
            },
            {
                "topic": "Forgot Voicemail PIN",
                "summary": "Customer cannot access their voicemail because they forgot their voicemail PIN. Requires resetting to a default PIN and setup guidance."
            },
            {
                "topic": "Verify Porting ID and PIN",
                "summary": "Customer is trying to port their number(s) to/from another carrier and needs to verify their exact Account Number and Porting PIN."
            },
            {
                "topic": "Account Merge & Master PIN Setup",
                "summary": "Customer has separate broadband and mobile accounts and wants to merge them under a single ID and setup a combined security PIN."
            }
        ],
        "Billing problems": [
            {
                "topic": "Unexpected International Roaming Charges",
                "summary": "Customer went abroad and noticed huge international roaming data charges. Frustrated. Needs explanation and potential proactive waiver/discount pass."
            },
            {
                "topic": "Promo Rate Expired Bill Increase",
                "summary": "Customer notices their bill increased by $10-$20. Agent discovers their 12-month promotional sign-up discount expired. Reviews contract and offers a new promotion."
            },
            {
                "topic": "Upgrade Ordered but Billing Erroneous",
                "summary": "Corporate/Consumer upgraded speed or services but was billed the new tier rate while technical speed remains at the old lower tier due to system sync lag. Requires billing credits."
            },
            {
                "topic": "Activation Fee Not Waived",
                "summary": "Customer noticed a $35 activation fee on a new line that they were promised would be waived. Wants a credit applied."
            },
            {
                "topic": "Corporate Tax Exemption Missing",
                "summary": "Corporate client is being charged state sales tax despite submitting tax-exempt status certificate. Wants taxes refunded and status validated."
            }
        ],
        "Technical issues e.g. outages and technical difficulties with equipment": [
            {
                "topic": "Complete Fiber Broadband Outage",
                "summary": "Customer working from home has a complete internet outage. Agent runs troubleshooting (modem/ONT restart, signal test), finds local storm-related physical fiber break, schedules/details field restoration."
            },
            {
                "topic": "TV Receiver Error Code E104",
                "summary": "TV set-top box showing error code. Troubleshooting involves cable checks, power cycle, and sending a box refresh/re-auth hit from the central network."
            },
            {
                "topic": "Poor Wi-Fi Coverage & Extender Order",
                "summary": "Customer complains of weak Wi-Fi signal on upper floor. Agent diagnoses configuration, explains frequency differences (2.4GHz vs 5GHz), and processes order for a mesh Wi-Fi extender node."
            },
            {
                "topic": "Enterprise Dedicated Line High Latency / Drops",
                "summary": "Corporate dedicated fiber link showing packet loss and high latency, impacting their office VoIP system. Requires hardware line tests and field engineering dispatch."
            },
            {
                "topic": "Poor Cellular Reception & Wi-Fi Calling Fix",
                "summary": "Customer drops mobile calls inside their basement or home office. Agent analyzes local map signal attenuation, explains limitations, and successfully enables and tests Wi-Fi Calling on their phone."
            }
        ],
        "New orders": [
            {
                "topic": "Add Unlimited Mobile Line & Phone Buy",
                "summary": "Consumer wants to add an additional mobile line for a family member and finance a new phone (e.g. iPhone 15 Pro) on monthly installments."
            },
            {
                "topic": "Branch Office Voice and Internet Setup",
                "summary": "Corporate manager orders broadband internet and cloud VoIP phone licenses for a new retail/satellite branch office. Requires professional technician install booking."
            },
            {
                "topic": "DSL to Fiber Upgrade Order",
                "summary": "Customer has old copper internet (DSL) and wants to upgrade to their newly available Fiber optic connection. Enrolls in plan, configures router upgrade, and sets terminal retrieval instructions."
            },
            {
                "topic": "Mobile Hotspot with Big Data Plan Purchase",
                "summary": "Consumer wants a standalone Wi-Fi hotspot (MiFi) device with 50GB data capacity plan for recreational travel. Sets up pricing and device orders."
            },
            {
                "topic": "Corporate Fleet Cellular Upgrade",
                "summary": "Corporate IT representative orders bulk cellular connection lines and devices (e.g., 10 new LTE tablets) for their field crew with enterprise pricing structure."
            }
        ],
        "Payments": [
            {
                "topic": "Autopay Failure & Update Expired Card",
                "summary": "Customer's automatic recurring payment failed because credit card on file expired. Customer wants to clear past balance manually and register a new card."
            },
            {
                "topic": "Direct Debit Setup for Autopay Discount",
                "summary": "Customer wants to configure direct monthly withdrawals from checking account (ACH) to secure the ongoing $10 monthly discount. Verifies account and routing."
            },
            {
                "topic": "Online Bank Transfer Delay & Suspension Hold",
                "summary": "Customer paid via online banking transfer but services were suspended or past due alert triggered. Agent validates transaction bank receipt, places temporary collection freeze, and schedules reactivation."
            },
            {
                "topic": "Hardship Split Payment Agreement",
                "summary": "Customer facing temporary hardship requests relief or extensions. Agent sets up a multi-month payment schedule (splitting arrears over next invoices) and waives late penalty."
            },
            {
                "topic": "Corporate Invoicing Large Wire Process",
                "summary": "Corporate finance department processes a large invoice payment via telephone electronic check (ACH). Agent verifies details and records transaction for ledger receipt."
            }
        ]
    }
    
    call_specs = []
    
    for i in range(1, 101):
        call_id = f"CALL-{i:04d}"
        
        # Sample random customer from weights pool
        customer = random.choice(choice_pool)
        
        # Sample random category
        category = random.choice(categories)
        
        # Sample random blueprint from category
        blueprint = random.choice(blueprints[category])
        
        # Sample random duration between 5 and 20 minutes
        duration = random.randint(5, 20)
        
        call_specs.append({
            "call_id": call_id,
            "customer_id": customer["customer_id"],
            "customer_name": customer["name"],
            "customer_type": customer["customer_type"],
            "category": category,
            "duration_minutes": duration,
            "topic": blueprint["topic"],
            "summary": blueprint["summary"]
        })
        
    with open("call_specs.json", "w") as f:
        json.dump(call_specs, f, indent=2)
        
    print(f"Generated 100 call specifications successfully and saved to call_specs.json!")
    
    # Let's print some quick specs statistics to stdout
    stats = {}
    for spec in call_specs:
        stats[spec["category"]] = stats.get(spec["category"], 0) + 1
    print("\nCall spec distribution by category:")
    for cat, count in stats.items():
        print(f"  - {cat}: {count} calls")
        
    user_counts = {}
    for spec in call_specs:
        user_counts[spec["customer_id"]] = user_counts.get(spec["customer_id"], 0) + 1
    represented_users = len(user_counts)
    print(f"\nUser representation statistics:")
    print(f"  - Total unique users in pool: {len(users)}")
    print(f"  - Total unique users represented in calls: {represented_users}")
    print(f"  - Max calls assigned to a single user: {max(user_counts.values())}")
    print(f"  - Min calls assigned to an active user: {min(user_counts.values())}")
    print(f"  - Users with 0 calls: {len(users) - represented_users}")
    
    return call_specs

if __name__ == "__main__":
    generate_specs()
