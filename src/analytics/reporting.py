import html
import re


def _text(value):
    value = html.escape(str(value)).replace('\n', ' ').replace('\r', ' ')
    return re.sub(r'([\\`*_{}\[\]()#+.!|>~-])', r'\\\1', value)


def render_report(collection):
    metrics = collection["metrics"]
    insights = collection.get("insights", {})
    average = metrics["average_rating"]
    lines = [f"# {_text(collection.get('app_name', 'App reviews'))}", '',
             f"Collection: `{collection['collection_id']}`", '',
             f"Storefront: {_text(collection.get('country', ''))}", '',
             f"Collected at: {_text(collection.get('collected_at', ''))}", '',
             f"Sample: {metrics['review_count']} reviews; source pool: {collection.get('pool_size', 'unknown')}.", '',
             f"Average rating: {average:.2f}/5" if average is not None else 'Average rating: unavailable', '',
             '| Rating | Count | Percentage |', '|---|---:|---:|']
    for rating, values in metrics['rating_distribution'].items():
        share = values['percentage']
        lines.append(f"| {rating} | {values['count']} | {share if share is not None else 'N/A'} |")
    lines += ['', '## Analysis status', '', _text(insights.get('status', 'not_run'))]
    for warning in collection.get('warnings', []):
        lines += ['', f"Warning: {_text(warning)}"]
    if collection.get('visualizations'):
        lines += ['', '## Visualizations', '']
        labels = {'rating_distribution': 'Rating distribution',
                  'sentiment_distribution': 'Sentiment distribution',
                  'top_issues': 'Most common complaint themes'}
        for name, url in collection['visualizations'].items():
            lines.append(f"- [{labels.get(name, name)}]({url})")
    if 'sentiment' in insights:
        lines += ['', '## Sentiment', '']
        for label, count in insights['sentiment']['counts'].items():
            lines.append(f'- {label}: {count}')
        lines += ['', '## Common keywords and phrases in negative reviews', '']
        for item in insights['keywords']['phrases']:
            lines.append(f"- {_text(item['phrase'])}: {item['review_count']} reviews ({item['percentage']}% of negative reviews)")
        lines += ['', '## Recommendations', '']
        recommendations = insights['recommendations']
        lines.append(f"Status: {_text(recommendations['status'])}")
        if recommendations.get('message'):
            lines += ['', _text(recommendations['message'])]
        topics = {t['topic_id']: t for t in insights['topics']}
        for item in recommendations['items']:
            topic = topics[item['topic_id']]
            lines += ['', f"### {_text(item.get('title', item['topic_id']))}", '',
                      f"{topic['review_count']} reviews ({topic['percentage']}% of the sample); "
                      f"average rating {topic.get('average_rating', 'N/A')}; priority "
                      f"{topic.get('priority_score', 'N/A')}/100 ({topic.get('seriousness', 'unknown')}).", '',
                      f"Observation: {_text(item['observation'])}", '',
                      f"Action: {_text(item['action'])}", '',
                      f"Verification: {_text(item['verification'])}", '', 'Evidence:', '']
            for evidence in topic['evidence']:
                if evidence['evidence_id'] in item['evidence_ids']:
                    lines.append(f"- Review {_text(evidence['review_id'])}: {_text(evidence['quote'])}")
        lines += ['', '## Topic evidence', '']
        for topic in insights['topics']:
            lines += [f"- {_text(topic['topic_id'])}: {topic['review_count']} reviews — {_text(topic['representative_quote'])}"]
    lines.append('')
    return '\n'.join(lines)
