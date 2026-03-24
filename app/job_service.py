import json

def get_jobs(role):

    with open("jobs.json") as f:
        jobs=json.load(f)

    matched=[]
    for j in jobs:
        if role.lower() in j["title"].lower():
            matched.append(j)

    return matched