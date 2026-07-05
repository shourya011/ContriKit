from django.db import models

class CheatSheetSection(models.Model):
    title = models.CharField(max_length=100)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'title']

    def __str__(self):
        return self.title

class CheatSheetCommand(models.Model):
    section = models.ForeignKey(CheatSheetSection, on_delete=models.CASCADE, related_name="commands")
    command = models.CharField(max_length=200)
    description = models.CharField(max_length=300)
    example = models.CharField(max_length=300, blank=True)
    order = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ['order', 'command']

    def __str__(self):
        return self.command
