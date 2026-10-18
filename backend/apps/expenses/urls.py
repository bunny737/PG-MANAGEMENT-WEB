from rest_framework.routers import SimpleRouter

from .views import ExpenseCategoryViewSet, ExpenseViewSet

router = SimpleRouter()
router.register('expenses', ExpenseViewSet, basename='expense')
router.register('expense-categories', ExpenseCategoryViewSet, basename='expense-category')

urlpatterns = router.urls
