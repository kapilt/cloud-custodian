.. _{{provider_name|upper}}_mode:

{{provider_name}} Execution Modes
---------------------------------

{% for m in modes %}

{{ename(m)}}
{{underline(ename(m), '+')}}
{{edoc(m)}}
{{eschema(m)}}

{% endfor %}
