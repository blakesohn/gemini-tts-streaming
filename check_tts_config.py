from google.cloud import texttospeech_v1beta1 as texttospeech
print(texttospeech.StreamingSynthesizeConfig.__module__)
print(dir(texttospeech.StreamingSynthesizeConfig))
try:
    print(texttospeech.StreamingSynthesizeConfig.__annotations__)
except:
    pass
