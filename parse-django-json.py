import pathlib as pth
import json
import os
from datetime import datetime

import click
import yaml
import markdownify

def get_content(json_filename, print_fl=False):
    fh = open(json_filename)
    json_contents = json.load(fh)

    content = {}

    model_fields = {
        "pages.page": ["title", "slug", "description", "content_model", "parent", "in_menus", "titles", "_order", "publish_date"],
        "pages.richtextpage": ["content"],
        "blog.blogpost": ["content", "title", "slug", "description", "publish_date", "user"],
        "pages.link": []
    }

    for item in json_contents:
        item_model = item["model"].split(".")[0]
        item_pk = item["pk"]
        if item_model == "blog":
            item_pk += 1000
        item_fields = {f: item["fields"][f] for f in model_fields[item["model"]]}
        item_fields["model"] = item_model
        if item_pk in content:
            content[item_pk] |= item_fields
        else:
            content[item_pk] = item_fields

    if print_fl:
        print(json.dumps(content, indent=2))

    return content

def make_hierrarchy(content, nodes=None, print_fl=False):
    """Make and print simple representation of hierarchy"""
    # If no base set of nodes provided, create a simple one using just the pk, 
    # title, and parent_id from content. Content could be substituted in instead
    # but is not as human readable. 
    if nodes is None:
        nodes = {}
        forest = []
        for pk, mfs  in content.items():
            print(pk, list(mfs.keys()), mfs['title'])
            if "parent" not in mfs:
                continue
            nodes[pk] = {
                "pk": pk, 
                'title': mfs['title'], 
                "slug": mfs["slug"], 
                # "model": mfs["model"],
                "fields": str(list(mfs.keys()))
            }

    for pk, mfs in content.items(): 
        if "parent" not in mfs:
            continue

        node = nodes[pk]
        parent = mfs["parent"]
        if parent is None:
            forest.append(node)
        else: 
            parent_node = nodes[parent]
            if not "children" in parent_node:
                parent_node["children"] = []
            parent_node["children"].append(node)

    if print_fl:
        print(json.dumps(forest, indent=2))
    
    return forest

def content_replace(bulk_content):
    replacements = {
        '"/eustace/static/': '"{{ site.baseurl }}/assets/',
        '"https://www.eustaceproject.eu/' : '"{{ site.baseurl }}/',
        '"{{ site.baseurl }}/eustace/static/': '"{{ site.baseurl }}/assets/',
        '"{{ site.baseurl }}/static/': '"{{ site.baseurl }}/assets/',
        'href="/': 'href="{{ site.baseurl }}/'
    }
    for k, v in replacements.items():
        bulk_content = bulk_content.replace(k, v)
    return bulk_content

# def convert_keys(fields):
common_conv = {
    "publish_date": ("date", lambda a: datetime.fromisoformat(a.replace("Z", ""))),
}
pages_conv = {
    "slug": ("permalink", lambda a: f"/{a}/"),
    "_order": "order",
}
blog_conv = {
    "slug": ("permalink", lambda a: f"/blog/{a}/"),
    "user": ("author", lambda a: a[0]),
}
preamble_keys = ["title", "description"]
def create_markdown(filename, fields, is_blog=False, markdownify_fl=False, content_replace_fl=True, 
                    **kwargs):
    preamble = {}
    if is_blog:
        conversion_dict = common_conv | blog_conv
    else:
        conversion_dict = common_conv | pages_conv

    # Convert keys from raw content
    for key, yaml_key in conversion_dict.items():
        # If conversion function given then apply it to fields value
        if isinstance(yaml_key, tuple) and len(yaml_key) == 2:
            preamble[yaml_key[0]] = yaml_key[1](fields[key])
        elif key in fields:    
            preamble[yaml_key] = fields[key]
    for key in preamble_keys:
        preamble[key] = fields[key]

    # Add kwargs to preamble dict    
    if kwargs:
        for key, value in kwargs.items():
            preamble[key] = value

    # Ensure directory structure exists before making file
    file_path = pth.Path(filename)
    os.makedirs(file_path.parent, exist_ok=True)

    with open(filename, "w") as f:
        # Write preamble to file
        f.write("---\n")
        yaml.dump(preamble, f)
        f.write("---\n\n")

        # Write content to file if present, and convert to markdown if specified
        if "content" in fields:
            bulk_content = fields["content"]
        elif "description" in fields:
            bulk_content = fields["description"]
        else:
            bulk_content = ""
        if content_replace_fl:
            bulk_content = content_replace(bulk_content)
        if markdownify_fl:
            bulk_content = markdownify.markdownify(bulk_content, heading_style="ATX")

        f.write(f"{bulk_content}\n")

def nest_markdowns(node, content, **kwargs):
    slug = node["slug"]
    if "children" in node:
        for child_node in node["children"]:
            nest_markdowns(child_node, content, **kwargs)
    create_markdown(f"{slug}.md", content[node["pk"]], **kwargs)
        
@click.command()
@click.option("--json_filename", default="django-json/eustace.json", 
              help="Path to json output file from Django")
@click.option("--project_dir", default="eustace-jekyll", 
              help="Directory to place converted pages and blog posts")
@click.option("--print_fl", default=False, is_flag=True, 
              help="Booelan flag to control whether script prints to stdout", )
@click.option("--generate_pages_fl", default=True, is_flag=True, 
              help="Booelan flag to control whether script (re)generates pages")
@click.option("--generate_blog_fl", default=True, is_flag=True,
              help="Booelan flag to control whether script (re)generates blog posts")
@click.option("--page_layout", default="base_eustace", 
              help="Layout file to use in preamble of pages")
@click.option("--blog_layout", default="post", 
              help="Layout file to use in preamble of blog posts")
def parse_django_json(json_filename, project_dir, print_fl, generate_pages_fl, 
                      generate_blog_fl, page_layout, blog_layout):
    content = get_content(json_filename, print_fl=print_fl)
    forest = make_hierrarchy(content, print_fl=print_fl)

    # Move to project dir and then make page hierarchy
    os.chdir(project_dir)
    if generate_pages_fl:
        for node in forest:
            nest_markdowns(node, content, layout=page_layout)

    if generate_blog_fl:
        # Make blog posts separately into the _posts folder, sub-separated by year 
        # of publication
        for pk, fields in content.items():
            if fields["model"] != "blog":
                continue
            dt = datetime.fromisoformat(fields["publish_date"].replace("Z", ""))
            create_markdown(f"_posts/{dt.year}-{dt.month}-{dt.day}-{fields['slug']}.md", fields, layout=blog_layout, 
                            is_blog=True)

if __name__ == "__main__":
    parse_django_json()