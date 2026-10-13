"""Deterministic, synthetic relational data. No personal customer data."""
import argparse
from datetime import datetime, timedelta
import numpy as np
import pandas as pd
from .config import RAW

CITIES = ["Boston", "Austin", "Seattle", "Chicago", "Denver", "Phoenix"]
CATEGORIES = ["Indian", "Italian", "Mexican", "American", "Thai", "Mediterranean"]
FOODS = [("Biryani", "Indian"), ("Paneer Tikka", "Indian"), ("Pizza", "Italian"), ("Pasta", "Italian"), ("Tacos", "Mexican"), ("Burrito", "Mexican"), ("Burger", "American"), ("Fries", "American"), ("Pad Thai", "Thai"), ("Green Curry", "Thai"), ("Falafel", "Mediterranean"), ("Shawarma", "Mediterranean")]

def generate(n_orders=3000, seed=42, output=RAW):
    if n_orders < 1: raise ValueError("n_orders must be positive")
    rng = np.random.default_rng(seed)
    output.mkdir(parents=True, exist_ok=True)
    users = pd.DataFrame([{"user_id": i, "user_name": f"Customer {i:04d}", "city": str(rng.choice(CITIES)), "signup_date": (datetime(2024,1,1)+timedelta(days=int(rng.integers(0,600)))).date().isoformat()} for i in range(1,401)])
    restaurants = pd.DataFrame([{"restaurant_id":i, "restaurant_name":f"{CATEGORIES[(i-1)%6]} Kitchen {i:02d}", "city":CITIES[(i-1)//6%6], "cuisine":CATEGORIES[(i-1)%6]} for i in range(1,37)])
    food = pd.DataFrame([{"food_id":i,"food_name":name,"category":category} for i,(name,category) in enumerate(FOODS,1)])
    menus=[]
    for r in restaurants.itertuples(index=False):
        for f in food.itertuples(index=False):
            if f.category==r.cuisine:
                menus.append({"menu_id":len(menus)+1,"restaurant_id":r.restaurant_id,"food_id":f.food_id,"price":float(rng.integers(9,24))+0.99})
    menu=pd.DataFrame(menus)
    menu_by_rest={int(k):v.to_dict('records') for k,v in menu.groupby('restaurant_id')}
    orders=[]; items=[]; reviews=[]
    for oid in range(1,n_orders+1):
        u=users.iloc[int(rng.integers(len(users)))]
        eligible=restaurants[restaurants.city==u.city]
        r=eligible.iloc[int(rng.integers(len(eligible)))]
        order_time=datetime(2025,1,1)+timedelta(minutes=int(rng.integers(0,365*24*60)))
        status=str(rng.choice(['delivered','cancelled','refunded'],p=[.88,.08,.04]))
        options=menu_by_rest[int(r.restaurant_id)]
        picks=rng.choice(len(options),size=int(rng.integers(1,min(3,len(options))+1)),replace=False)
        subtotal=0.
        for idx in picks:
            m=options[int(idx)]; quantity=int(rng.integers(1,4)); amount=round(m['price']*quantity,2)
            items.append({'order_item_id':len(items)+1,'order_id':oid,'menu_id':int(m['menu_id']),'quantity':quantity,'unit_price':m['price'],'line_total':amount})
            subtotal+=amount
        fee=round(float(rng.uniform(1.5,5.5)),2)
        total=round(subtotal+fee,2)
        delivery_minutes=int(rng.integers(18,75)) if status=='delivered' else None
        orders.append({'order_id':oid,'user_id':int(u.user_id),'restaurant_id':int(r.restaurant_id),'ordered_at':order_time.isoformat(timespec='seconds'),'status':status,'payment_method':str(rng.choice(['card','wallet','cash'])),'delivery_minutes':delivery_minutes,'delivery_fee':fee,'order_total':total})
        if status=='delivered' and rng.random()<.55:
            rating=int(rng.choice([1,2,3,4,5],p=[.04,.08,.15,.37,.36]))
            reviews.append({'review_id':len(reviews)+1,'order_id':oid,'user_id':int(u.user_id),'restaurant_id':int(r.restaurant_id),'rating':rating,'review_text':{1:'Very disappointing',2:'Could be better',3:'Average experience',4:'Good food',5:'Excellent meal'}[rating]})
    data={'users':users,'restaurant':restaurants,'food':food,'menu':menu,'orders':pd.DataFrame(orders),'order_items':pd.DataFrame(items),'reviews':pd.DataFrame(reviews,columns=['review_id','order_id','user_id','restaurant_id','rating','review_text'])}
    for name,df in data.items(): df.to_csv(output/f'{name}.csv',index=False)
    return {name:len(df) for name,df in data.items()}

if __name__=='__main__':
    parser=argparse.ArgumentParser(); parser.add_argument('--orders',type=int,default=3000); parser.add_argument('--seed',type=int,default=42)
    args=parser.parse_args(); print(generate(args.orders,args.seed))
